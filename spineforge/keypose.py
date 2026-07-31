"""关键姿势选取（对应 RedrawSpine 的 preprocess 阶段）。

问题：一张 attachment 贴图上的纹素，在 rest pose 里往往只有一部分露得出来——
手臂内侧、裙子背面、被躯干挡住的袖子，这些区域在正面站姿下根本没有对应像素，
只重绘一张正面图，那些纹素就会一直是白的。

做法：贪心。先在 rest pose 上把所有可见纹素标记为"已画"，然后遍历全部动画的
全部采样时刻，找出"还没画过的纹素露出最多"的那一帧，把它加进序列并同样标记，
如此反复，直到某一轮的新增收益低到不值得再来一次 SD 推理为止。

产物写在 ``build/<角色>/redraw/``：每个姿势一份 UV 映射 + mask + ctrl + canny，
外加一份 ``manifest.json`` 记录序列顺序、部件 ID 表和覆盖率统计。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spineforge import raster
from spineforge.concept import Concept, Outfit, resolve_group_ids
from spineforge.config import Config
from spineforge.raster import OCCLUDER_ID, TEXEL_DRAWN
from spineforge.runtime import Skeleton


@dataclass
class Pose:
    """序列里的一个姿势。``animation=None`` 表示 rest pose。"""

    name: str
    animation: str | None
    time: float
    new_texels: int


def assign_ids(concept: Concept, outfit: Outfit | None) -> tuple[dict[str, int], dict[str, int]]:
    """给部件分配 UV ID 与 ControlNet 分组 ID。

    需要重绘的部件拿 1..N（0 留给"空"），其余部件拿 ``OCCLUDER_ID``：
    它们照常遮挡，但不会把自己的纹素写进 UV 图，因此不会被 SD 改动。
    """
    redraw = concept.redraw_parts(outfit)
    if len(redraw) > 254:
        raise ValueError(f"[{concept.id}] 需要重绘的部件超过 254 个，UV 图的 8 位 ID 装不下")

    ids: dict[str, int] = {}
    for i, part in enumerate(redraw, start=1):
        ids[part.name] = i
    for part in concept.parts:
        ids.setdefault(part.name, OCCLUDER_ID)

    group_raw = resolve_group_ids(concept, redraw)
    groups: dict[str, int] = {p.name: group_raw[p.name] for p in redraw}
    for part in concept.parts:
        groups.setdefault(part.name, OCCLUDER_ID)
    return ids, groups


def initial_states(textures: dict[str, np.ndarray], cfg: Config) -> dict[str, np.ndarray]:
    return {
        name: raster.alpha_state(tex, cfg.low_alpha_threshold)
        for name, tex in textures.items()
    }


def mark_drawn(uv: np.ndarray, states: dict[str, np.ndarray],
               id_to_name: dict[int, str]) -> int:
    """把本姿势覆盖到的纹素标记为"已画"，返回新增数量。"""
    nonzero = uv[uv != 0]
    if nonzero.size == 0:
        return 0
    gained = 0
    slot_ids = (nonzero >> np.uint32(24)).astype(np.int64)
    texels = (nonzero & np.uint32(0xFFFFFF)).astype(np.int64)
    for sid in np.unique(slot_ids):
        name = id_to_name.get(int(sid))
        if name is None:
            continue
        state = states[name]
        idx = np.unique(texels[slot_ids == sid])
        flat = state.reshape(-1)
        gained += int(np.count_nonzero(flat[idx] != TEXEL_DRAWN))
        flat[idx] = TEXEL_DRAWN
    return gained


def _count_undrawn(uv: np.ndarray) -> int:
    return int(np.count_nonzero(uv))


def select_poses(skeleton: Skeleton, states: dict[str, np.ndarray],
                 ids: dict[str, int], id_to_name: dict[int, str],
                 width: int, height: int, cfg: Config) -> list[Pose]:
    """贪心挑选关键姿势序列。第一个永远是 rest pose。"""
    skeleton.pose()
    uv = raster.render_uv(skeleton, states, ids, width, height)
    gained = mark_drawn(uv, states, id_to_name)
    poses = [Pose(name="restPose", animation=None, time=0.0, new_texels=gained)]

    first_gain = 0
    while len(poses) < cfg.keypose_max_count:
        best: tuple[int, str, float] | None = None
        for anim in skeleton.animations:
            for t in skeleton.frames(anim, cfg.keypose_sample_step):
                skeleton.pose(anim, t)
                probe = raster.render_uv(skeleton, states, ids, width, height,
                                         only_undrawn=True)
                count = _count_undrawn(probe)
                if best is None or count > best[0]:
                    best = (count, anim, t)

        if best is None:
            break
        count, anim, t = best
        if first_gain == 0:
            first_gain = count
        threshold = max(cfg.keypose_min_gain, int(first_gain * cfg.keypose_min_gain_ratio))
        if count < threshold:
            break

        skeleton.pose(anim, t)
        uv = raster.render_uv(skeleton, states, ids, width, height)
        gained = mark_drawn(uv, states, id_to_name)
        poses.append(Pose(name=f"{anim}_{t:g}", animation=anim, time=t, new_texels=gained))

    skeleton.pose()
    return poses


def coverage_report(states: dict[str, np.ndarray], ids: dict[str, int]) -> dict[str, Any]:
    """统计每个待重绘部件被姿势序列覆盖到的纹素比例。

    覆盖率低的部件说明现有动画里它就没怎么露出来，多半得手工补一个展示姿势，
    否则那块贴图上会留下没被 SD 画过的白区。
    """
    per_part: dict[str, float] = {}
    total = drawn = 0
    for name, slot_id in ids.items():
        if slot_id == OCCLUDER_ID or name not in states:
            continue
        state = states[name]
        opaque = int(np.count_nonzero(state != raster.TEXEL_TRANSPARENT))
        hit = int(np.count_nonzero(state == TEXEL_DRAWN))
        total += opaque
        drawn += hit
        per_part[name] = round(hit / opaque, 4) if opaque else 0.0
    return {
        "overall": round(drawn / total, 4) if total else 0.0,
        "per_part": dict(sorted(per_part.items(), key=lambda kv: kv[1])),
    }


def preprocess(concept: Concept, skeleton: Skeleton, textures: dict[str, np.ndarray],
               outfit: Outfit | None, out_dir: Path, cfg: Config) -> dict[str, Any]:
    """跑完整个预处理并落盘，返回 manifest。"""
    from PIL import Image

    width, height = concept.canvas.width, concept.canvas.height
    ids, groups = assign_ids(concept, outfit)
    id_to_name = {v: k for k, v in ids.items() if v != OCCLUDER_ID}

    states = initial_states(textures, cfg)
    poses = select_poses(skeleton, states, ids, id_to_name, width, height, cfg)
    coverage = coverage_report(states, ids)

    out_dir.mkdir(parents=True, exist_ok=True)
    # 重新走一遍序列，这次把每个姿势的 UV / mask / ctrl / canny 落盘。
    # mask 依赖"到此为止画过什么"，所以状态要从头再算一次。
    states = initial_states(textures, cfg)
    for pose in poses:
        skeleton.pose(pose.animation, pose.time)
        undrawn = raster.render_uv(skeleton, states, ids, width, height, only_undrawn=True)
        uv = raster.render_uv(skeleton, states, ids, width, height)
        ctrl = raster.render_ctrl(skeleton, states, groups, width, height)
        canny = raster.edges_from_ids(ctrl)

        np.save(out_dir / f"{pose.name}.uv.npy", uv)
        Image.fromarray(raster.uv_to_mask(undrawn)).save(out_dir / f"{pose.name}@mask.png")
        Image.fromarray(ctrl).save(out_dir / f"{pose.name}@ctrl.png")
        Image.fromarray(canny).save(out_dir / f"{pose.name}@canny.png")
        mark_drawn(uv, states, id_to_name)
    skeleton.pose()

    manifest = {
        "concept": concept.id,
        "outfit": outfit.name if outfit else None,
        "canvas": [width, height],
        "downscale": cfg.downscale,
        "ids": ids,
        "groups": groups,
        "sequence": [asdict(p) for p in poses],
        "coverage": coverage,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
