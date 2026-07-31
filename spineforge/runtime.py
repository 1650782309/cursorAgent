"""skeleton.json 的最小运行时：骨骼层级求解 + 动画采样 + 四边形输出。

只实现本工作流用得到的子集——region attachment、rotate/translate/scale 时间轴、
线性插值、normal 继承模式。够用于把任意姿势光栅化出来，也就够驱动重绘流程。

输出的四边形坐标已经换算到画布像素空间（左上角为原点、y 向下），
后续光栅器不再需要关心 Spine 的世界坐标系。
"""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np


@dataclass
class Bone:
    name: str
    parent: str | None
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    length: float = 0.0
    # 世界变换矩阵 [[a, b], [c, d]] 与世界位置，由 update_world 填。
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    wx: float = 0.0
    wy: float = 0.0


@dataclass
class Region:
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    width: float = 0.0
    height: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0


@dataclass
class Slot:
    name: str
    bone: str
    attachment: str | None


@dataclass
class Quad:
    """一个 region attachment 在当前姿势下占据的画布四边形。"""

    slot: str
    attachment: str
    # 顺序固定为 左下、左上、右上、右下（贴图坐标系下）
    corners: np.ndarray          # (4, 2) 画布像素，y 向下
    uvs: np.ndarray = field(     # (4, 2) 归一化 uv，(0,0) 是贴图左上角
        default_factory=lambda: np.array(
            [[0.0, 1.0], [0.0, 0.0], [1.0, 0.0], [1.0, 1.0]], dtype=np.float64
        )
    )


class Skeleton:
    def __init__(self, data: dict[str, Any], origin: tuple[float, float]) -> None:
        self.data = data
        self.origin_x, self.origin_y = origin

        self.bones: dict[str, Bone] = {}
        self.bone_order: list[str] = []
        for raw in data["bones"]:
            bone = Bone(
                name=raw["name"],
                parent=raw.get("parent"),
                x=float(raw.get("x", 0.0)),
                y=float(raw.get("y", 0.0)),
                rotation=float(raw.get("rotation", 0.0)),
                scale_x=float(raw.get("scaleX", 1.0)),
                scale_y=float(raw.get("scaleY", 1.0)),
                length=float(raw.get("length", 0.0)),
            )
            self.bones[bone.name] = bone
            self.bone_order.append(bone.name)

        self.slots = [
            Slot(name=s["name"], bone=s["bone"], attachment=s.get("attachment"))
            for s in data["slots"]
        ]

        skin = data["skins"][0]["attachments"]
        self.regions: dict[tuple[str, str], Region] = {}
        for slot_name, entries in skin.items():
            for att_name, raw in entries.items():
                self.regions[(slot_name, att_name)] = Region(
                    x=float(raw.get("x", 0.0)),
                    y=float(raw.get("y", 0.0)),
                    rotation=float(raw.get("rotation", 0.0)),
                    width=float(raw["width"]),
                    height=float(raw["height"]),
                    scale_x=float(raw.get("scaleX", 1.0)),
                    scale_y=float(raw.get("scaleY", 1.0)),
                )

        self.animations: dict[str, Any] = data.get("animations", {})
        self._setup = {
            name: (b.x, b.y, b.rotation, b.scale_x, b.scale_y)
            for name, b in self.bones.items()
        }
        self.pose()

    # ------------------------------------------------------------------ 加载
    @classmethod
    def load(cls, skeleton_path: Path, origin: tuple[float, float]) -> "Skeleton":
        data = json.loads(Path(skeleton_path).read_text(encoding="utf-8"))
        return cls(data, origin)

    # ------------------------------------------------------------------ 姿势
    def duration(self, animation: str) -> float:
        from spineforge.animation import animation_duration

        return animation_duration(self.animations[animation])

    def pose(self, animation: str | None = None, time: float = 0.0) -> None:
        """把骨骼摆到指定动画的指定时刻；``animation=None`` 表示 setup pose。"""
        for name, (x, y, rot, sx, sy) in self._setup.items():
            b = self.bones[name]
            b.x, b.y, b.rotation, b.scale_x, b.scale_y = x, y, rot, sx, sy

        if animation is not None:
            tracks = self.animations[animation].get("bones", {})
            for bone_name, channels in tracks.items():
                bone = self.bones.get(bone_name)
                if bone is None:
                    continue
                if "rotate" in channels:
                    bone.rotation += _lerp_frames(channels["rotate"], time, ("angle",))[0]
                if "translate" in channels:
                    dx, dy = _lerp_frames(channels["translate"], time, ("x", "y"))
                    bone.x += dx
                    bone.y += dy
                if "scale" in channels:
                    sx, sy = _lerp_frames(channels["scale"], time, ("x", "y"), default=1.0)
                    bone.scale_x *= sx
                    bone.scale_y *= sy

        self._update_world()

    def _update_world(self) -> None:
        for name in self.bone_order:
            bone = self.bones[name]
            rad = math.radians(bone.rotation)
            cos, sin = math.cos(rad), math.sin(rad)
            la = cos * bone.scale_x
            lb = -sin * bone.scale_y
            lc = sin * bone.scale_x
            ld = cos * bone.scale_y

            if bone.parent is None:
                bone.a, bone.b, bone.c, bone.d = la, lb, lc, ld
                bone.wx, bone.wy = bone.x, bone.y
                continue

            p = self.bones[bone.parent]
            bone.a = p.a * la + p.b * lc
            bone.b = p.a * lb + p.b * ld
            bone.c = p.c * la + p.d * lc
            bone.d = p.c * lb + p.d * ld
            bone.wx = p.a * bone.x + p.b * bone.y + p.wx
            bone.wy = p.c * bone.x + p.d * bone.y + p.wy

    # ------------------------------------------------------------------ 输出
    def quads(self, only: Iterable[str] | None = None) -> list[Quad]:
        """按绘制顺序返回当前姿势下所有 attachment 的四边形。"""
        allow = set(only) if only is not None else None
        out: list[Quad] = []
        for slot in self.slots:
            if slot.attachment is None:
                continue
            if allow is not None and slot.name not in allow:
                continue
            region = self.regions.get((slot.name, slot.attachment))
            if region is None:
                continue
            out.append(Quad(slot.name, slot.attachment,
                            self._region_corners(self.bones[slot.bone], region)))
        return out

    def _region_corners(self, bone: Bone, r: Region) -> np.ndarray:
        hw = r.width / 2.0 * r.scale_x
        hh = r.height / 2.0 * r.scale_y
        rad = math.radians(r.rotation)
        cos, sin = math.cos(rad), math.sin(rad)

        # 贴图四角在骨骼局部空间的位置（左下、左上、右上、右下）
        local = ((-hw, -hh), (-hw, hh), (hw, hh), (hw, -hh))
        corners = np.empty((4, 2), dtype=np.float64)
        for i, (lx, ly) in enumerate(local):
            ox = lx * cos - ly * sin + r.x
            oy = lx * sin + ly * cos + r.y
            wx = ox * bone.a + oy * bone.b + bone.wx
            wy = ox * bone.c + oy * bone.d + bone.wy
            # Spine 世界坐标 y 向上；画布像素 y 向下。
            corners[i] = (wx + self.origin_x, self.origin_y - wy)
        return corners

    def bounds(self, animation: str | None = None, step: float = 0.05) -> tuple[float, float, float, float]:
        """返回 (min_x, min_y, max_x, max_y) 画布像素包围盒。

        ``animation=None`` 时扫描全部动画的全部采样时刻，用于检查画布是否兜得住。
        """
        names = [animation] if animation else list(self.animations)
        lo = np.array([np.inf, np.inf])
        hi = np.array([-np.inf, -np.inf])

        def accumulate() -> None:
            nonlocal lo, hi
            for q in self.quads():
                lo = np.minimum(lo, q.corners.min(axis=0))
                hi = np.maximum(hi, q.corners.max(axis=0))

        self.pose()
        accumulate()
        for name in names:
            duration = self.duration(name)
            t = 0.0
            while t <= duration + 1e-9:
                self.pose(name, t)
                accumulate()
                t += step
        self.pose()
        return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])

    def frames(self, animation: str, step: float) -> list[float]:
        """动画的采样时刻列表（不含末尾重复帧）。"""
        duration = self.duration(animation)
        n = max(1, int(round(duration / step)))
        return [round(i * duration / n, 5) for i in range(n)]


def _lerp_frames(frames: list[dict[str, float]], time: float,
                 keys: tuple[str, ...], default: float = 0.0) -> tuple[float, ...]:
    """在关键帧序列上做线性插值，越界时取端点值。"""
    if not frames:
        return tuple(default for _ in keys)
    times = [f["time"] for f in frames]
    if time <= times[0]:
        return tuple(float(frames[0].get(k, default)) for k in keys)
    if time >= times[-1]:
        return tuple(float(frames[-1].get(k, default)) for k in keys)

    i = bisect.bisect_right(times, time) - 1
    a, b = frames[i], frames[i + 1]
    span = b["time"] - a["time"]
    t = 0.0 if span <= 0 else (time - a["time"]) / span
    return tuple(
        float(a.get(k, default)) + (float(b.get(k, default)) - float(a.get(k, default))) * t
        for k in keys
    )
