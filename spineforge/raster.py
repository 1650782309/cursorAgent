"""软件光栅器：把当前姿势画成颜色图 / UV 映射图 / ControlNet 控制图。

对应 RedrawSpine 里的三套 shader（rgb.glsl、uv_redraw.glsl、ctrl.glsl），
这里用 numpy 复刻，因此不需要 GPU、离屏上下文和 CUDA。

三种渲染目标
------------
``COLOR``  RGBA8，正常 alpha 混合，就是玩家看到的画面。
``UV``     uint32，每个像素记录 ``(部件ID << 24) | 纹素下标``。
           这张图是整个换装流程的关键：它把"屏幕像素"和"贴图纹素"一一对上，
           重绘完成后照着它反查就能把新画的颜色写回 attachment。
``CTRL``   uint8，每个像素填部件所属分组的 ID。它的边界就是部件轮廓，
           送去做 canny 后作为 ControlNet 输入，锁住重绘时的形状。
"""

from __future__ import annotations

from enum import Enum
from typing import Iterator, Mapping

import numpy as np

from spineforge.runtime import Quad, Skeleton

# 纹素状态（对应原实现里贴图 red 通道的三个取值）
TEXEL_TRANSPARENT = 0
TEXEL_DRAWN = 128
TEXEL_UNDRAWN = 255

# shader 里的丢弃阈值，换算成 0~255
UV_ALPHA_CUTOFF = 13     # 0.05：宁可把边缘写进上层部件的透明纹素，也别写进下层的不透明纹素
CTRL_ALPHA_CUTOFF = 51   # 0.20：在"贴着轮廓"和"胖一圈"之间取折中
UNDRAWN_CUTOFF = 140     # 0.55：只保留还没画过的纹素

# 不参与重绘的部件用这个 ID。它们照样参与光栅化，但只往缓冲里写 0，
# 于是被它们挡住的像素不会被归给下层部件——挡脸的头发不会把脸的 UV 抹出来。
OCCLUDER_ID = 0


class Target(Enum):
    COLOR = "color"
    UV = "uv"
    CTRL = "ctrl"


def _fragments(quad: Quad, width: int, height: int) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """把四边形拆成两个三角形逐个光栅化，产出 (ys, xs, u, v)。"""
    corners = quad.corners
    uvs = quad.uvs
    for tri in ((0, 1, 2), (0, 2, 3)):
        p0, p1, p2 = corners[tri[0]], corners[tri[1]], corners[tri[2]]
        area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])
        if abs(area) < 1e-9:
            continue

        x_lo = max(int(np.floor(min(p0[0], p1[0], p2[0]))), 0)
        x_hi = min(int(np.ceil(max(p0[0], p1[0], p2[0]))) + 1, width)
        y_lo = max(int(np.floor(min(p0[1], p1[1], p2[1]))), 0)
        y_hi = min(int(np.ceil(max(p0[1], p1[1], p2[1]))) + 1, height)
        if x_lo >= x_hi or y_lo >= y_hi:
            continue

        xs = np.arange(x_lo, x_hi) + 0.5
        ys = np.arange(y_lo, y_hi) + 0.5
        gx, gy = np.meshgrid(xs, ys)

        w0 = ((p1[0] - p0[0]) * (gy - p0[1]) - (gx - p0[0]) * (p1[1] - p0[1])) / area
        w1 = ((gx - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (gy - p0[1])) / area
        inside = (w0 >= 0) & (w1 >= 0) & (w0 + w1 <= 1)
        if not inside.any():
            continue

        b1 = w1[inside]
        b2 = w0[inside]
        b0 = 1.0 - b1 - b2
        uv = (b0[:, None] * uvs[tri[0]] + b1[:, None] * uvs[tri[1]]
              + b2[:, None] * uvs[tri[2]])

        iy, ix = np.nonzero(inside)
        yield iy + y_lo, ix + x_lo, uv[:, 0], uv[:, 1]


def _sample_indices(u: np.ndarray, v: np.ndarray, tw: int, th: int) -> tuple[np.ndarray, np.ndarray]:
    """最近邻采样。必须是最近邻——UV 图记录的是整数纹素下标，不能被插值糊掉。"""
    tx = np.clip((u * tw).astype(np.int64), 0, tw - 1)
    ty = np.clip((v * th).astype(np.int64), 0, th - 1)
    return tx, ty


def render_color(skeleton: Skeleton, textures: Mapping[str, np.ndarray],
                 width: int, height: int,
                 background: tuple[int, int, int, int] = (0, 0, 0, 0)) -> np.ndarray:
    """渲染 RGBA 画面，按 slot 顺序做标准 alpha 混合。"""
    canvas = np.zeros((height, width, 4), dtype=np.float32)
    canvas[..., 0] = background[0]
    canvas[..., 1] = background[1]
    canvas[..., 2] = background[2]
    canvas[..., 3] = background[3]

    for quad in skeleton.quads():
        tex = textures.get(quad.attachment)
        if tex is None:
            continue
        th, tw = tex.shape[:2]
        texf = tex.astype(np.float32)
        for ys, xs, u, v in _fragments(quad, width, height):
            tx, ty = _sample_indices(u, v, tw, th)
            src = texf[ty, tx]
            alpha = (src[:, 3:4] / 255.0)
            dst = canvas[ys, xs]
            out_a = alpha[:, 0] + dst[:, 3] / 255.0 * (1.0 - alpha[:, 0])
            rgb = src[:, :3] * alpha + dst[:, :3] * (1.0 - alpha)
            canvas[ys, xs, :3] = rgb
            canvas[ys, xs, 3] = np.clip(out_a * 255.0, 0, 255)

    return np.clip(canvas, 0, 255).astype(np.uint8)


def render_uv(skeleton: Skeleton, states: Mapping[str, np.ndarray],
              ids: Mapping[str, int], width: int, height: int,
              only_undrawn: bool = False) -> np.ndarray:
    """渲染 UV 映射图。

    ``states[attachment]`` 是该贴图的纹素状态图（0 透明 / 128 已画 / 255 未画）。
    ``only_undrawn=True`` 时只保留还没画过的纹素——这正是关键姿势选取里
    "本姿势能新露出多少纹素"的度量方式。
    """
    out = np.zeros((height, width), dtype=np.uint32)
    for quad in skeleton.quads():
        state = states.get(quad.attachment)
        slot_id = ids.get(quad.slot)
        if state is None or slot_id is None:
            continue
        th, tw = state.shape[:2]
        for ys, xs, u, v in _fragments(quad, width, height):
            tx, ty = _sample_indices(u, v, tw, th)
            red = state[ty, tx]
            visible = red >= UV_ALPHA_CUTOFF
            if not visible.any():
                continue
            # 已画过的纹素以及不重绘的部件仍然要写 0：它们挡住了后面的东西，
            # 不写 0 的话被遮住的像素会被错误地算到下层部件头上。
            emit = visible & (red >= UNDRAWN_CUTOFF) if only_undrawn else visible
            if slot_id == OCCLUDER_ID:
                emit = np.zeros_like(visible)
            out[ys[visible], xs[visible]] = 0
            if not emit.any():
                continue
            idx = (ty[emit].astype(np.uint32) * np.uint32(tw) + tx[emit].astype(np.uint32))
            out[ys[emit], xs[emit]] = (np.uint32(slot_id) << np.uint32(24)) | idx
    return out


def render_ctrl(skeleton: Skeleton, states: Mapping[str, np.ndarray],
                group_ids: Mapping[str, int], width: int, height: int) -> np.ndarray:
    """渲染 ControlNet 控制图：每个像素填所属分组 ID。"""
    out = np.zeros((height, width), dtype=np.uint8)
    for quad in skeleton.quads():
        state = states.get(quad.attachment)
        gid = group_ids.get(quad.slot)
        if state is None or gid is None:
            continue
        th, tw = state.shape[:2]
        value = np.uint8((gid * 3) % 256)
        for ys, xs, u, v in _fragments(quad, width, height):
            tx, ty = _sample_indices(u, v, tw, th)
            keep = state[ty, tx] >= CTRL_ALPHA_CUTOFF
            if keep.any():
                out[ys[keep], xs[keep]] = value
    return out


def alpha_state(rgba: np.ndarray, low_alpha_threshold: int) -> np.ndarray:
    """把 RGBA 贴图转成初始纹素状态图：够不透明的纹素记为"未画"，其余为透明。"""
    return np.where(rgba[..., 3] > low_alpha_threshold,
                    np.uint8(TEXEL_UNDRAWN), np.uint8(TEXEL_TRANSPARENT))


def uv_to_mask(uv: np.ndarray) -> np.ndarray:
    """UV 图 -> inpaint mask（白色区域交给 SD 重画）。"""
    return np.where(uv != 0, np.uint8(255), np.uint8(0))


def edges_from_ids(ctrl: np.ndarray) -> np.ndarray:
    """从分组 ID 图直接求边界，替代对灰度图跑 canny。

    ID 图是分片常量的，边界就是"和邻居 ID 不同"的像素——比 canny 更干净，
    也不会像 canny 那样在渐变色块内部误检出线条。同组部件共享 ID，
    所以它们之间的接缝天然不会产生边。
    """
    out = np.zeros_like(ctrl, dtype=np.uint8)
    for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
        diff = ctrl != np.roll(ctrl, shift, axis=axis)
        out[diff] = 255
    # np.roll 是环绕的，画布四边会被误判成边界，抹掉。
    out[0, :] = out[-1, :] = out[:, 0] = out[:, -1] = 0
    return out
