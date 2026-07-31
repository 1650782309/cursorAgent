"""程序化动画生成。

每个生成器把一组解析式（正弦摆动、缓动抬手……）在若干关键帧时刻上采样，
写成 Spine 的 rotate / translate / scale 时间轴。采样点之间用线性插值，
所以导出的 JSON 在 Spine 编辑器里播放和在本仓库的运行时里播放是一致的。

时间轴数值的语义与 Spine 一致：rotate / translate 是相对 setup pose 的偏移量，
scale 是相对 setup 缩放的倍率。
"""

from __future__ import annotations

import math
from typing import Any, Callable

from spineforge.concept import Concept

TAU = math.tau


def _keys(duration: float, count: int, fn: Callable[[float], Any]) -> list[tuple[float, Any]]:
    """在 [0, duration] 上均匀采 count+1 个点（含首尾，便于循环闭合）。"""
    return [(round(i * duration / count, 5), fn(i / count)) for i in range(count + 1)]


class _Builder:
    """收集各骨骼的时间轴，最后吐出 Spine 动画 JSON。"""

    def __init__(self, duration: float, keys: int) -> None:
        self.duration = duration
        self.keys = keys
        self.bones: dict[str, dict[str, list[dict[str, float]]]] = {}

    def _track(self, bone: str, channel: str) -> list[dict[str, float]]:
        return self.bones.setdefault(bone, {}).setdefault(channel, [])

    def rotate(self, bone: str, fn: Callable[[float], float]) -> None:
        track = self._track(bone, "rotate")
        for t, v in _keys(self.duration, self.keys, fn):
            track.append({"time": t, "angle": round(v, 3)})

    def translate(self, bone: str, fn: Callable[[float], tuple[float, float]]) -> None:
        track = self._track(bone, "translate")
        for t, v in _keys(self.duration, self.keys, fn):
            track.append({"time": t, "x": round(v[0], 3), "y": round(v[1], 3)})

    def scale(self, bone: str, fn: Callable[[float], tuple[float, float]]) -> None:
        track = self._track(bone, "scale")
        for t, v in _keys(self.duration, self.keys, fn):
            track.append({"time": t, "x": round(v[0], 4), "y": round(v[1], 4)})

    def to_json(self) -> dict[str, Any]:
        return {"bones": self.bones}


def _appendages(b: _Builder, tail: float, wing: float, cycles: float = 1.0) -> None:
    """给尾巴和翅膀加摆动。

    设定集里墨的尾巴"尾尖动作独立于表情，作画时当作独立演员处理"，
    所以尾巴第二节比第一节相位滞后，看起来像被甩出去的。
    没有这些部位的角色，骨骼上没挂 attachment，这些轨道等于不存在。
    """
    b.rotate("tail_01", lambda p: tail * math.sin(TAU * cycles * p))
    b.rotate("tail_02", lambda p: tail * 1.6 * math.sin(TAU * cycles * p - 0.9))
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # 两侧反相，翅膀才是"扇"而不是整体平移
        b.rotate(f"wing_{side}", lambda p, s=sign: s * wing * math.sin(TAU * cycles * p))
        b.rotate(f"wing_{side}_02",
                 lambda p, s=sign: s * wing * 1.4 * math.sin(TAU * cycles * p - 0.7))


def _idle(concept: Concept) -> _Builder:
    u = concept.rig["unit"]
    b = _Builder(duration=2.0, keys=12)
    b.translate("hip", lambda p: (0.0, 0.03 * u * math.sin(TAU * p)))
    b.rotate("torso", lambda p: 1.6 * math.sin(TAU * p))
    b.rotate("chest", lambda p: 1.2 * math.sin(TAU * p + 0.5))
    b.rotate("head", lambda p: -1.8 * math.sin(TAU * p + 0.9))
    for side, sign in (("l", 1.0), ("r", -1.0)):
        b.rotate(f"upper_arm_{side}", lambda p, s=sign: s * 3.5 * math.sin(TAU * p + 0.6))
        b.rotate(f"lower_arm_{side}", lambda p, s=sign: s * 2.5 * math.sin(TAU * p + 1.1))
    _appendages(b, tail=6.0, wing=4.0)
    return b


def _breath(concept: Concept) -> _Builder:
    u = concept.rig["unit"]
    b = _Builder(duration=2.4, keys=12)
    b.scale("chest", lambda p: (1.0 + 0.03 * math.sin(TAU * p), 1.0 + 0.05 * math.sin(TAU * p)))
    b.translate("head", lambda p: (0.0, 0.02 * u * math.sin(TAU * p)))
    b.rotate("torso", lambda p: 1.0 * math.sin(TAU * p))
    for side, sign in (("l", 1.0), ("r", -1.0)):
        b.rotate(f"upper_arm_{side}", lambda p, s=sign: s * 5.0 * math.sin(TAU * p))
    _appendages(b, tail=4.0, wing=6.0)
    return b


def _gait(concept: Concept, duration: float, swing: float, knee: float,
          arm: float, lean: float, bob: float) -> _Builder:
    """走 / 跑共用的步态生成器，只是幅度不同。

    ``bob`` 是骨盆上下起伏的幅度，单位是头长——``rig.unit`` 就是一个头长的像素数，
    所以同一套数值在 5.5 头身和 8.0 头身的角色上都是合理的比例。
    """
    u = concept.rig["unit"]
    b = _Builder(duration=duration, keys=16)
    b.translate("hip", lambda p: (0.0, bob * u * math.cos(2 * TAU * p)))
    b.rotate("torso", lambda p: lean + 2.0 * math.sin(2 * TAU * p))

    for side, phase in (("l", 0.0), ("r", math.pi)):
        b.rotate(f"thigh_{side}", lambda p, ph=phase: swing * math.sin(TAU * p + ph))
        # 膝盖只能向后弯，所以取单侧的余弦而不是完整正弦。
        b.rotate(f"shin_{side}",
                 lambda p, ph=phase: -knee * (0.5 + 0.5 * math.sin(TAU * p + ph - math.pi / 2)))
        b.rotate(f"foot_{side}", lambda p, ph=phase: 12.0 * math.sin(TAU * p + ph + 0.9))
        # 手臂与同侧腿反相
        b.rotate(f"upper_arm_{side}",
                 lambda p, ph=phase: -arm * math.sin(TAU * p + ph))
        b.rotate(f"lower_arm_{side}",
                 lambda p, ph=phase: -arm * 0.45 * (0.6 + 0.4 * math.sin(TAU * p + ph + 1.2)))
    _appendages(b, tail=swing * 0.5, wing=arm * 0.4, cycles=2.0)
    return b


def _walk(concept: Concept) -> _Builder:
    return _gait(concept, duration=1.0, swing=26.0, knee=22.0, arm=20.0, lean=1.5, bob=0.04)


def _run(concept: Concept) -> _Builder:
    return _gait(concept, duration=0.7, swing=46.0, knee=52.0, arm=38.0, lean=-9.0, bob=0.09)


def _ease(p: float, start: float, end: float) -> float:
    """把 p 在 [start, end] 区间内映射成 0->1 的平滑缓动，区间外取端值。"""
    if p <= start:
        return 0.0
    if p >= end:
        return 1.0
    t = (p - start) / (end - start)
    return t * t * (3.0 - 2.0 * t)


def _wave(concept: Concept) -> _Builder:
    b = _Builder(duration=1.8, keys=18)
    # 右臂抬到头侧后左右摆手，收势时放下。
    def raise_amount(p: float) -> float:
        return _ease(p, 0.0, 0.22) - _ease(p, 0.80, 1.0)

    b.rotate("upper_arm_r", lambda p: -138.0 * raise_amount(p))
    b.rotate("lower_arm_r",
             lambda p: -35.0 * raise_amount(p) + 26.0 * raise_amount(p) * math.sin(TAU * 2.5 * p))
    b.rotate("hand_r", lambda p: 18.0 * raise_amount(p) * math.sin(TAU * 2.5 * p + 0.4))
    b.rotate("upper_arm_l", lambda p: 8.0 * math.sin(TAU * p))
    b.rotate("torso", lambda p: 3.0 * raise_amount(p))
    b.rotate("head", lambda p: -5.0 * raise_amount(p))
    b.rotate("chest", lambda p: 2.0 * math.sin(TAU * p))
    _appendages(b, tail=14.0, wing=10.0, cycles=2.0)
    return b


def _cast(concept: Concept) -> _Builder:
    u = concept.rig["unit"]
    b = _Builder(duration=2.0, keys=20)
    # 蓄力（后仰）-> 推出（前倾），双臂前举，把平时被躯干挡住的袖子内侧露出来。
    def charge(p: float) -> float:
        return _ease(p, 0.05, 0.45) - _ease(p, 0.55, 0.9)

    b.rotate("torso", lambda p: -7.0 * charge(p) + 10.0 * _ease(p, 0.45, 0.6) * (1 - _ease(p, 0.7, 0.95)))
    b.rotate("chest", lambda p: -4.0 * charge(p))
    b.rotate("head", lambda p: -6.0 * charge(p))
    b.translate("hip", lambda p: (0.0, -0.05 * u * charge(p)))
    b.rotate("upper_arm_r", lambda p: -95.0 * charge(p))
    b.rotate("lower_arm_r", lambda p: -40.0 * charge(p))
    b.rotate("upper_arm_l", lambda p: 70.0 * charge(p))
    b.rotate("lower_arm_l", lambda p: 30.0 * charge(p))
    b.rotate("thigh_l", lambda p: 10.0 * charge(p))
    b.rotate("thigh_r", lambda p: -12.0 * charge(p))
    b.rotate("shin_r", lambda p: -18.0 * charge(p))
    # 起势时翅膀张开、尾巴绷紧，收势时回位
    b.rotate("tail_01", lambda p: -22.0 * charge(p))
    b.rotate("tail_02", lambda p: -30.0 * charge(p))
    for side, sign in (("l", 1.0), ("r", -1.0)):
        b.rotate(f"wing_{side}", lambda p, s=sign: s * 26.0 * charge(p))
        b.rotate(f"wing_{side}_02", lambda p, s=sign: s * 18.0 * charge(p))
    return b


GENERATORS: dict[str, Callable[[Concept], _Builder]] = {
    "idle": _idle,
    "breath": _breath,
    "walk": _walk,
    "run": _run,
    "wave": _wave,
    "cast": _cast,
}


def build_animations(concept: Concept) -> dict[str, Any]:
    """按概念的 ``animations`` 列表生成全部动画。

    生成器只会给骨架上真实存在的骨骼写时间轴——概念可以裁掉某些骨骼，
    多余的轨道会被静默丢弃而不是让运行时崩掉。
    """
    from spineforge.skeleton import build_bones

    known = {b.name for b in build_bones(concept)}
    out: dict[str, Any] = {}
    for name in concept.animations:
        if name not in GENERATORS:
            raise ValueError(
                f"[{concept.id}] 未知动画 {name!r}，可选：{sorted(GENERATORS)}"
            )
        builder = GENERATORS[name](concept)
        anim = builder.to_json()
        anim["bones"] = {k: v for k, v in anim["bones"].items() if k in known}
        out[name] = anim
    return out


def animation_duration(anim: dict[str, Any]) -> float:
    """从时间轴反推动画时长。"""
    end = 0.0
    for tracks in anim.get("bones", {}).values():
        for frames in tracks.values():
            if frames:
                end = max(end, float(frames[-1]["time"]))
    return end
