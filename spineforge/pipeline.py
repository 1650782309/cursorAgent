"""端到端编排：build -> preprocess -> reskin -> preview。

每一段都把产物落在 ``build/<角色>/`` 下，且只读取上一段的落盘结果，
所以任何一段都能单独重跑、单独检查，出问题时能定位到具体环节。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from spineforge import keypose, partgen, raster, skeleton as skel, writeback
from spineforge.concept import Concept, Outfit
from spineforge.config import Config
from spineforge.raster import OCCLUDER_ID
from spineforge.runtime import Skeleton
from spineforge.sd import RedrawRequest, get_backend

Logger = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# --------------------------------------------------------------------- 工具
def load_textures(images_dir: Path) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for path in sorted(images_dir.glob("*.png")):
        out[path.stem] = np.asarray(Image.open(path).convert("RGBA")).copy()
    return out


def save_textures(textures: dict[str, np.ndarray], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, tex in textures.items():
        Image.fromarray(tex, mode="RGBA").save(out_dir / f"{name}.png")


def on_white(rgba: np.ndarray) -> Image.Image:
    """把带 alpha 的渲染结果压到白底上。

    SD 的 img2img 只吃三通道；直接丢掉 alpha 会让透明区域变成黑色，
    黑底会顺着 mask 边缘把重绘结果染暗。
    """
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    rgb = rgba[..., :3].astype(np.float32) * a + 255.0 * (1.0 - a)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")


def load_skeleton(concept: Concept, cfg: Config) -> Skeleton:
    path = cfg.character_dir(concept.id) / "skeleton.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} 不存在，请先执行 build")
    return Skeleton.load(path, (concept.canvas.origin_x, concept.canvas.origin_y))


def redraw_dir(concept: Concept, outfit: Outfit | None, cfg: Config) -> Path:
    """预处理产物按 outfit 分目录存。

    不同 outfit 的 ``targets`` 不同，需要重绘的部件集合就不同，
    进而选出的关键姿势序列也不同，不能共用一份缓存。
    """
    return cfg.redraw_dir(concept.id) / (outfit.name if outfit else "_all")


# --------------------------------------------------------------------- build
@dataclass
class BuildResult:
    images: int
    skeleton_path: Path
    atlas_path: Path
    bounds: tuple[float, float, float, float]
    fits_canvas: bool


def build(concept: Concept, cfg: Config, log: Logger = _noop) -> BuildResult:
    """概念 -> attachment 贴图 + skeleton.json + fake.atlas。"""
    char_dir = cfg.character_dir(concept.id)
    images_dir = cfg.images_dir(concept.id)

    log(f"生成 {len(concept.parts)} 个部件贴图 -> {images_dir}")
    written = partgen.generate_images(concept, images_dir)

    skeleton_path = skel.write_skeleton(concept, char_dir)
    atlas_path = skel.write_atlas(concept, images_dir)
    log(f"骨架 {skeleton_path.name}，动画 {list(concept.animations)}")

    sk = Skeleton.load(skeleton_path, (concept.canvas.origin_x, concept.canvas.origin_y))
    bounds = sk.bounds()
    fits = (bounds[0] >= 0 and bounds[1] >= 0
            and bounds[2] <= concept.canvas.width and bounds[3] <= concept.canvas.height)
    if not fits:
        log(f"警告：全动画包围盒 {tuple(round(b, 1) for b in bounds)} 超出画布 "
            f"{concept.canvas.width}x{concept.canvas.height}，超出部分不会参与重绘")

    unit = 8 * cfg.downscale
    if concept.canvas.width % unit or concept.canvas.height % unit:
        log(f"警告：画布尺寸不是 {unit} 的倍数，SD 会自行 padding 导致回写错位")

    return BuildResult(len(written), skeleton_path, atlas_path, bounds, fits)


# ---------------------------------------------------------------- preprocess
def preprocess(concept: Concept, outfit: Outfit | None, cfg: Config,
               log: Logger = _noop) -> dict[str, Any]:
    """选关键姿势并产出 UV / mask / ctrl / canny。"""
    sk = load_skeleton(concept, cfg)
    textures = load_textures(cfg.images_dir(concept.id))
    out_dir = redraw_dir(concept, outfit, cfg)

    log(f"扫描 {len(sk.animations)} 段动画寻找关键姿势（步长 {cfg.keypose_sample_step}s）")
    manifest = keypose.preprocess(concept, sk, textures, outfit, out_dir, cfg)

    for pose in manifest["sequence"]:
        log(f"  {pose['name']:<16} 新增纹素 {pose['new_texels']}")
    cov = manifest["coverage"]
    log(f"整体覆盖率 {cov['overall']:.1%}")
    worst = list(cov["per_part"].items())[:3]
    if worst and worst[0][1] < 0.8:
        log("覆盖率偏低的部件：" + "，".join(f"{n} {v:.0%}" for n, v in worst))
    return manifest


def ensure_preprocess(concept: Concept, outfit: Outfit | None, cfg: Config,
                      log: Logger = _noop, force: bool = False) -> dict[str, Any]:
    path = redraw_dir(concept, outfit, cfg) / "manifest.json"
    if not force and path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return preprocess(concept, outfit, cfg, log)


# -------------------------------------------------------------------- reskin
@dataclass
class ReskinResult:
    out_dir: Path
    poses: int
    written_texels: int
    rejected_edge: int
    rejected_dup: int
    flooded: int
    seconds: float


def reskin(concept: Concept, outfit: Outfit, seed: int, backend_name: str,
           cfg: Config, log: Logger = _noop, keep_steps: bool = True) -> ReskinResult:
    """按关键姿势序列逐帧重绘，并把结果回写成一整套新贴图。"""
    started = time.time()
    manifest = ensure_preprocess(concept, outfit, cfg, log)
    sk = load_skeleton(concept, cfg)

    ids: dict[str, int] = manifest["ids"]
    groups: dict[str, int] = manifest["groups"]
    id_to_name = {v: k for k, v in ids.items() if v != OCCLUDER_ID}
    width, height = manifest["canvas"]

    textures = load_textures(cfg.images_dir(concept.id))
    out_dir = cfg.skin_dir(concept.id, outfit.name, seed)
    steps_dir = out_dir / "steps"
    if keep_steps:
        steps_dir.mkdir(parents=True, exist_ok=True)

    # 底图取原始贴图的 rest pose 渲染：SD 需要一张有结构的图才画得稳，
    # 全白底图会让它自由发挥出完全不成形的东西。
    sk.pose()
    template = on_white(raster.render_color(sk, textures, width, height))

    # 待重绘的贴图先洗白，避免没被覆盖到的纹素露出旧配色。
    for name, slot_id in ids.items():
        if slot_id != OCCLUDER_ID and name in textures:
            textures[name] = partgen.whiten(textures[name], cfg.low_alpha_threshold)

    written = {
        name: writeback.initial_written(tex, cfg.low_alpha_threshold)
        for name, tex in textures.items()
    }

    backend = get_backend(backend_name, concept, outfit, cfg)
    denoise = outfit.denoising_strength or cfg.denoising_strength
    log(f"后端 {backend.name}，seed {seed}，重绘强度 {denoise}")

    totals = writeback.WriteStats(0, 0, 0)
    sequence = manifest["sequence"]
    for i, pose in enumerate(sequence):
        sk.pose(pose["animation"], pose["time"])

        uv = raster.render_uv(sk, written, ids, width, height, only_undrawn=True)
        if not uv.any():
            log(f"  [{i}] {pose['name']} 无待重绘像素，跳过")
            continue
        mask = Image.fromarray(raster.uv_to_mask(uv), mode="L")
        ctrl = raster.render_ctrl(sk, written, groups, width, height)
        control = Image.fromarray(raster.edges_from_ids(ctrl), mode="L")
        base = template if i == 0 else on_white(
            raster.render_color(sk, textures, width, height)
        )

        result = backend.redraw(RedrawRequest(
            image=base, mask=mask, control=control,
            prompt=outfit.prompt, negative_prompt=outfit.negative_prompt,
            seed=seed, denoising_strength=denoise,
        ))
        if result.size != (width, height):
            raise RuntimeError(
                f"后端返回了 {result.size} 的图，画布是 {(width, height)}；"
                "尺寸不一致会让 UV 回写整体错位"
            )

        stats = writeback.apply_frame(
            uv, np.asarray(result.convert("RGB")), textures, written, id_to_name, cfg
        )
        totals = writeback.WriteStats(
            totals.written + stats.written,
            totals.rejected_edge + stats.rejected_edge,
            totals.rejected_dup + stats.rejected_dup,
        )
        log(f"  [{i}] {pose['name']:<16} 回写 {stats.written} 纹素"
            f"（边缘剔除 {stats.rejected_edge}，重复 {stats.rejected_dup}）")

        if keep_steps:
            base.save(steps_dir / f"{i:02d}_{pose['name']}_base.png")
            mask.save(steps_dir / f"{i:02d}_{pose['name']}_mask.png")
            control.save(steps_dir / f"{i:02d}_{pose['name']}_canny.png")
            result.save(steps_dir / f"{i:02d}_{pose['name']}_redraw.png")

        if i == 0:
            # 洗白后贴图上只剩描边是深色的，先清掉孤立描边点，
            # 否则最后的邻域扩散会把整块布料染灰。
            for name, slot_id in ids.items():
                if slot_id != OCCLUDER_ID and name in textures:
                    writeback.clean_outliner(textures[name])

    flooded = 0
    for name, slot_id in ids.items():
        if slot_id != OCCLUDER_ID and name in textures:
            flooded += writeback.flood_unwritten(textures[name], written[name])
    log(f"邻域扩散补齐 {flooded} 个未覆盖纹素")

    save_textures(textures, out_dir / "images")
    skel.write_atlas(concept, out_dir / "images")

    result = ReskinResult(
        out_dir=out_dir,
        poses=len(sequence),
        written_texels=totals.written,
        rejected_edge=totals.rejected_edge,
        rejected_dup=totals.rejected_dup,
        flooded=flooded,
        seconds=round(time.time() - started, 2),
    )
    (out_dir / "report.json").write_text(
        json.dumps(
            {
                "concept": concept.id,
                "outfit": outfit.name,
                "seed": seed,
                "backend": backend.name,
                "poses": result.poses,
                "written_texels": result.written_texels,
                "rejected_edge": result.rejected_edge,
                "rejected_dup": result.rejected_dup,
                "flooded": result.flooded,
                "seconds": result.seconds,
                "coverage": manifest["coverage"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


# ------------------------------------------------------------------- preview
def preview(concept: Concept, animation: str, images_dir: Path, out_path: Path,
            cfg: Config, fps: int = 24, log: Logger = _noop) -> Path:
    """把一段动画渲染成 GIF，用来肉眼确认换装后动起来没有穿帮。"""
    sk = load_skeleton(concept, cfg)
    if animation not in sk.animations:
        raise ValueError(f"[{concept.id}] 没有动画 {animation!r}，可选：{list(sk.animations)}")

    textures = load_textures(images_dir)
    width, height = concept.canvas.width, concept.canvas.height
    duration = sk.duration(animation)
    count = max(2, int(round(duration * fps)))

    frames: list[Image.Image] = []
    for i in range(count):
        sk.pose(animation, i * duration / count)
        frames.append(on_white(raster.render_color(sk, textures, width, height)))
    sk.pose()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=int(1000 / fps),
        loop=0,
        optimize=False,
    )
    log(f"{animation}: {count} 帧 -> {out_path}")
    return out_path


def contact_sheet(concept: Concept, images_dir: Path, out_path: Path, cfg: Config,
                  columns: int = 4) -> Path:
    """把关键姿势拼成一张对比图，方便一眼看完整套换装。"""
    sk = load_skeleton(concept, cfg)
    textures = load_textures(images_dir)
    width, height = concept.canvas.width, concept.canvas.height

    poses: list[tuple[str | None, float]] = [(None, 0.0)]
    for anim in sk.animations:
        duration = sk.duration(anim)
        poses += [(anim, duration * f) for f in (0.0, 0.25, 0.5, 0.75)]

    scale = 4
    tw, th = width // scale, height // scale
    rows = (len(poses) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tw, rows * th), "white")
    for i, (anim, t) in enumerate(poses):
        sk.pose(anim, t)
        img = on_white(raster.render_color(sk, textures, width, height))
        sheet.paste(img.resize((tw, th), Image.LANCZOS), ((i % columns) * tw, (i // columns) * th))
    sk.pose()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path
