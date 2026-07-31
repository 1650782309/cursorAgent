"""从概念生成 attachment 贴图。

美术组真实项目里这一步是 Photoshop 出图，工作流的其余部分不关心贴图哪来的，
只要求"一个部件一张带 alpha 的 PNG"。这里用程序化绘制补上这一环，
让整条流水线在没有原画资产的情况下也能端到端跑通、回归测试。

每张图都是：形状遮罩 + 纵向明暗渐变 + 一圈描边，2x2 超采样抗锯齿。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from spineforge.concept import PART_PADDING, Concept, Part

PAD = PART_PADDING
SS = 2   # 超采样倍数


def _shape_coverage(shape: str, w: int, h: int) -> np.ndarray:
    """返回 [0,1] 的覆盖率图，尺寸 (h, w)。

    内部在 SS 倍分辨率上求二值遮罩再降采样，得到抗锯齿边缘。
    坐标系：x 向右，y 向上，都归一化到 [-1, 1]。
    """
    hw, hh = w * SS, h * SS
    xs = (np.arange(hw) + 0.5) / hw * 2.0 - 1.0
    ys = 1.0 - (np.arange(hh) + 0.5) / hh * 2.0
    x = xs[None, :]
    y = ys[:, None]

    if shape == "ellipse":
        mask = (x * x + y * y) <= 1.0

    elif shape == "capsule":
        # 竖直胶囊：中段是矩形，上下各一个半圆帽。
        r = min(1.0, w / max(h, 1))          # 半宽 / 半高
        core = max(0.0, 1.0 - r)             # 矩形段在 y 上的半长
        dy = np.maximum(np.abs(y) - core, 0.0)
        mask = (x * x + (dy / max(r, 1e-6)) ** 2) <= 1.0

    elif shape == "plate":
        # 圆角矩形，圆角半径取短边的 35%
        rr = 0.35
        ax = np.maximum(np.abs(x) - (1.0 - rr), 0.0) / rr
        ay = np.maximum(np.abs(y) - (1.0 - rr), 0.0) / rr
        mask = (ax * ax + ay * ay) <= 1.0

    elif shape == "blade":
        # 长条武器：根部满宽，越靠近顶端越收，最后收成尖。
        t = (y + 1.0) * 0.5                  # 0=底 1=顶
        half = np.clip(1.0 - 0.85 * np.clip((t - 0.72) / 0.28, 0, 1) ** 1.4, 0.05, 1.0)
        half = half * (1.0 - 0.12 * np.clip((0.18 - t) / 0.18, 0, 1))
        mask = np.abs(x) <= half

    elif shape == "bell":
        # 裙子 / 头发：上窄下宽，底边略呈弧形。
        t = (1.0 - y) * 0.5                  # 0=顶 1=底
        half = 0.45 + 0.55 * t ** 0.75
        bottom = 1.0 - 0.10 * (1.0 - x * x)
        mask = (np.abs(x) <= half) & (y >= -bottom)

    elif shape == "cape":
        # 披风：比 bell 更宽，两侧微内凹，底部开叉。
        t = (1.0 - y) * 0.5
        half = 0.40 + 0.62 * t - 0.10 * math.sin(math.pi * 0.5) * t * (1 - t)
        notch = 0.18 * np.clip(1.0 - np.abs(x) / 0.30, 0, 1)
        mask = (np.abs(x) <= half) & (y >= -1.0 + notch)

    elif shape == "cone":
        # 尖角：雨衣的硬尖帽檐、猫耳。底边平、顶点尖。
        t = (1.0 - y) * 0.5
        mask = np.abs(x) <= np.clip(t ** 0.9, 0.0, 1.0)

    elif shape == "wing":
        # 羽翼：根部在贴图底边中央，向上并向一侧弧出，中段最宽、翼尖收拢。
        # 用一条弯曲的中心线加纺锤形宽度描出来，保证是"自然的鸟类弧线"，
        # 而不是几何能量翼。另一侧用部件的 mirror 开关翻过来。
        t = np.clip((y + 1.0) * 0.5, 0.0, 1.0)
        center = 0.85 * t ** 1.25 - 0.10
        half = 0.52 * np.sin(np.pi * np.clip(t, 0.0, 1.0) ** 0.8)
        mask = np.abs(x - center) <= np.maximum(half, 1e-6)

    elif shape == "ring":
        # 光轮：细圆环。
        r2 = x * x + y * y
        mask = (r2 <= 1.0) & (r2 >= 0.62 ** 2)

    else:
        raise ValueError(f"未知形状 {shape!r}")

    cov = mask.astype(np.float32).reshape(h, SS, w, SS).mean(axis=(1, 3))
    return cov


def _outline(cov: np.ndarray) -> np.ndarray:
    """由覆盖率图求出"贴着内边缘的一圈"，用于画描边。"""
    inner = cov >= 0.99
    shrunk = inner.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        shrunk &= np.roll(inner, (dy, dx), axis=(0, 1))
    shrunk[0, :] = shrunk[-1, :] = shrunk[:, 0] = shrunk[:, -1] = False
    return (cov > 0.02) & ~shrunk


def render_part(part: Part, rgb: tuple[int, int, int]) -> np.ndarray:
    """画出单个部件的 RGBA 贴图。尺寸由部件在概念里的像素尺寸 + PAD 决定。"""
    w, h = part.pixel_size
    cov = np.zeros((h, w), dtype=np.float32)
    cov[PAD:h - PAD, PAD:w - PAD] = _shape_coverage(part.shape, w - 2 * PAD, h - 2 * PAD)

    base = np.array(rgb, dtype=np.float32)
    # 纵向渐变：顶部提亮、底部压暗，给平涂色块一点体积感。
    ramp = np.linspace(1.0, -1.0, h, dtype=np.float32)[:, None, None]
    shade = 1.0 + part.shade * ramp * 0.6
    color = np.clip(np.broadcast_to(base, (h, w, 3)) * shade, 0, 255)

    edge = _outline(cov)
    color[edge] = np.clip(base * 0.55, 0, 255)

    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[..., :3] = color.astype(np.uint8)
    out[..., 3] = (np.clip(cov, 0, 1) * 255).astype(np.uint8)
    return out


def generate_images(concept: Concept, out_dir: Path) -> dict[str, Path]:
    """生成全部 attachment PNG，返回 ``{部件名: 路径}``。"""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for part in concept.parts:
        img = render_part(part, concept.rgb(part.color))
        path = out_dir / f"{part.name}.png"
        Image.fromarray(img, mode="RGBA").save(path)
        written[part.name] = path
    return written


def whiten(rgba: np.ndarray, alpha_threshold: int = 5) -> np.ndarray:
    """把不透明像素刷成纯白。

    重绘开始前要先把待重绘的 attachment 洗白：SD 画出来的颜色是直接覆盖上去的，
    留着旧颜色会在没被任何关键姿势覆盖到的纹素上露出上一套衣服的残影。
    """
    out = rgba.copy()
    solid = out[..., 3] > alpha_threshold
    out[solid, 0:3] = 255
    return out
