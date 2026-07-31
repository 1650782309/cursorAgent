"""由概念生成 Spine 骨架（bones / slots / skins）。

坐标约定
--------
导出的 JSON 遵循 Spine 惯例：骨骼的局部 +x 指向骨骼长度方向，角度逆时针为正，
世界 +y 向上，root 在角色脚下。

但概念文件里写 attachment 偏移时用的是更直观的"部件坐标系"：
+Y = 沿骨骼向前（大腿骨就是向下），+X = 面向该方向时的右手边。
两者差一个 -90° 旋转，转换集中在 :func:`_attachment_transform` 一处。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from spineforge.concept import Concept

SPINE_VERSION = "3.8.99"


class BoneDef:
    __slots__ = ("name", "parent", "x", "y", "rotation", "length", "world_rotation")

    def __init__(self, name, parent, x, y, rotation, length, world_rotation):
        self.name = name
        self.parent = parent
        self.x = x
        self.y = y
        self.rotation = rotation
        self.length = length
        self.world_rotation = world_rotation


def build_bones(concept: Concept) -> list[BoneDef]:
    """摆出人形 T-pose 骨架。

    ``rig`` 里的长度是单位制，这里统一乘上 ``rig.unit`` 变成 Spine 单位（=像素）。
    """
    r = concept.rig
    u = r["unit"]

    def L(key: str) -> float:
        return r[key] * u

    bones: list[BoneDef] = []
    world_rot: dict[str, float] = {}

    def add(name: str, parent: str | None, local_x: float, local_y: float,
            world_deg: float, length: float = 0.0) -> None:
        parent_world = world_rot.get(parent, 0.0) if parent else 0.0
        bones.append(BoneDef(name, parent, local_x, local_y,
                             world_deg - parent_world, length, world_deg))
        world_rot[name] = world_deg

    add("root", None, 0.0, 0.0, 0.0)
    # 躯干链：全部指向正上方（世界 90°）。它们的局部 +y 因此指向世界左侧，
    # 所以下面往左右两侧挂骨骼时，局部 y 为正=屏幕左、为负=屏幕右。
    add("hip", "root", 0.0, L("hip_height"), 90.0)
    add("torso", "hip", 0.0, 0.0, 90.0, L("torso"))
    add("chest", "torso", L("torso"), 0.0, 90.0, L("chest"))
    add("neck", "chest", L("chest"), 0.0, 90.0, L("neck"))
    add("head", "neck", L("neck"), 0.0, 90.0, L("head"))

    span_sh = L("shoulder_span") / 2.0
    span_hip = L("hip_span") / 2.0

    for side, sign in (("l", 1.0), ("r", -1.0)):
        # 手臂：自然下垂并微微外张。
        out = 8.0 * sign
        add(f"upper_arm_{side}", "chest", L("chest") * 0.88, span_sh * sign,
            -90.0 - out, L("upper_arm"))
        add(f"lower_arm_{side}", f"upper_arm_{side}", L("upper_arm"), 0.0,
            -90.0 - out * 0.5, L("lower_arm"))
        add(f"hand_{side}", f"lower_arm_{side}", L("lower_arm"), 0.0,
            -90.0, L("hand"))

        # 腿：接近垂直，脚尖朝屏幕右。
        add(f"thigh_{side}", "hip", 0.0, span_hip * sign, -90.0 - 3.0 * sign, L("thigh"))
        add(f"shin_{side}", f"thigh_{side}", L("thigh"), 0.0, -90.0 - 1.0 * sign, L("shin"))
        add(f"foot_{side}", f"shin_{side}", L("shin"), 0.0, 0.0, L("foot"))

    return bones


def _attachment_transform(part, unit: float) -> tuple[float, float, float]:
    """部件坐标系 -> Spine 骨骼局部坐标系。

    部件坐标系绕原点顺时针转 90° 就是骨骼坐标系，于是 (ox, oy) -> (oy, -ox)，
    区域图的旋转同样减去 90°（让贴图的"上"对齐骨骼的前进方向）。
    """
    ox, oy = part.offset[0] * unit, part.offset[1] * unit
    return oy, -ox, part.rotation - 90.0


def build_skeleton(concept: Concept) -> dict[str, Any]:
    """组装完整 skeleton.json（动画留空，由 animation 模块填）。"""
    from spineforge.animation import build_animations

    bones = build_bones(concept)
    unit = concept.rig["unit"]

    bone_json: list[dict[str, Any]] = []
    for b in bones:
        entry: dict[str, Any] = {"name": b.name}
        if b.parent:
            entry["parent"] = b.parent
        for key, value in (("x", b.x), ("y", b.y), ("rotation", b.rotation),
                           ("length", b.length)):
            if abs(value) > 1e-6:
                entry[key] = round(value, 4)
        bone_json.append(entry)

    ordered = concept.draw_order()
    slots = [{"name": p.name, "bone": p.bone, "attachment": p.name} for p in ordered]

    attachments: dict[str, Any] = {}
    for p in ordered:
        x, y, rot = _attachment_transform(p, unit)
        w, h = p.pixel_size
        attachments[p.name] = {
            p.name: {
                "x": round(x, 4),
                "y": round(y, 4),
                "rotation": round(rot, 4),
                "width": w,
                "height": h,
            }
        }

    return {
        "skeleton": {
            "hash": concept.id,
            "spine": SPINE_VERSION,
            "x": -concept.canvas.origin_x,
            "y": -(concept.canvas.height - concept.canvas.origin_y),
            "width": concept.canvas.width,
            "height": concept.canvas.height,
            "images": "./images/",
            "audio": "",
        },
        "bones": bone_json,
        "slots": slots,
        "skins": [{"name": "default", "attachments": attachments}],
        "animations": build_animations(concept),
    }


def write_skeleton(concept: Concept, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "skeleton.json"
    path.write_text(
        json.dumps(build_skeleton(concept), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def write_atlas(concept: Concept, images_dir: Path) -> Path:
    """写一份"假 atlas"。

    整条流水线是一个部件一张 PNG，不做真正的图集打包；atlas 只用来告诉运行时
    每个 region 的尺寸。这与 RedrawSpine 里的 ``fake.atlas`` 是同一个作用。
    """
    lines: list[str] = []
    for part in concept.draw_order():
        w, h = part.pixel_size
        lines += [
            f"{part.name}.png",
            f"size: {w},{h}",
            "filter: Linear,Linear",
            f"{part.name}",
            f"  bounds: 0,0,{w},{h}",
            "",
        ]
    path = images_dir / "fake.atlas"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def degrees_wrap(angle: float) -> float:
    """把角度归一到 (-180, 180]，插值前用来避免绕远路。"""
    a = math.fmod(angle + 180.0, 360.0)
    if a <= 0:
        a += 360.0
    return a - 180.0
