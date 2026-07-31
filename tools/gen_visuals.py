#!/usr/bin/env python3
"""从 palettes.json 生成角色配色卡与头身比对照图的 SVG。

用法:
    python3 tools/gen_visuals.py
输出:
    assets/palettes/<id>.svg
    assets/proportions.svg
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "tools" / "palettes.json"
PALETTE_DIR = ROOT / "assets" / "palettes"

FONT = (
    "'Hiragino Sans','Noto Sans CJK SC','Noto Sans SC','Source Han Sans SC',"
    "'PingFang SC','Microsoft YaHei',sans-serif"
)
INK = "#2A2530"
PAPER = "#FBFAF7"
RULE = "#DCD8D2"
MUTED = "#8A8580"

SW = 96          # 色块宽
SH = 72          # 色块高
GAP = 10
PAD = 32
ROW_H = SH + 46  # 单组行高（含标签）


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def readable_on(hex_color: str) -> str:
    """按相对亮度挑选叠字颜色，保证色号在浅色与深色块上都可读。"""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return INK if luminance > 0.45 else "#FFFFFF"


def palette_svg(spec: dict) -> str:
    groups = spec["groups"]
    cols = max(len(g["swatches"]) for g in groups)
    width = PAD * 2 + cols * SW + (cols - 1) * GAP
    width = max(width, 620)
    header = 96
    height = header + len(groups) * ROW_H + PAD

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{esc(spec["name"])} 配色卡">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
        f'<rect x="0" y="0" width="8" height="{height}" fill="{spec["accent"]}"/>',
        f'<text x="{PAD}" y="46" font-family="{FONT}" font-size="24" font-weight="700" '
        f'fill="{INK}">{esc(spec["name"])}</text>',
        f'<text x="{PAD}" y="70" font-family="{FONT}" font-size="13" '
        f'fill="{MUTED}">{esc(spec["subtitle"])}</text>',
        f'<text x="{width - PAD}" y="46" text-anchor="end" font-family="{FONT}" '
        f'font-size="12" fill="{MUTED}">COLOR SETTING</text>',
        f'<line x1="{PAD}" y1="{header - 14}" x2="{width - PAD}" y2="{header - 14}" '
        f'stroke="{RULE}" stroke-width="1"/>',
    ]

    y = header
    for group in groups:
        out.append(
            f'<text x="{PAD}" y="{y + 14}" font-family="{FONT}" font-size="13" '
            f'font-weight="600" fill="{INK}">{esc(group["label"])}</text>'
        )
        box_y = y + 26
        for i, sw in enumerate(group["swatches"]):
            x = PAD + i * (SW + GAP)
            fg = readable_on(sw["hex"])
            out.append(
                f'<rect x="{x}" y="{box_y}" width="{SW}" height="{SH}" rx="4" '
                f'fill="{sw["hex"]}" stroke="{RULE}" stroke-width="1"/>'
            )
            out.append(
                f'<text x="{x + 10}" y="{box_y + 26}" font-family="{FONT}" '
                f'font-size="12" font-weight="600" fill="{fg}">{sw["hex"]}</text>'
            )
            out.append(
                f'<text x="{x + 10}" y="{box_y + 46}" font-family="{FONT}" '
                f'font-size="11" fill="{fg}" opacity="0.85">{esc(sw["use"])}</text>'
            )
        y += ROW_H

    out.append("</svg>")
    return "\n".join(out)


# --- 头身比对照图 ---------------------------------------------------------

FIGURES = [
    # id, 名字, 身高cm, 头身比, 主色, 剪影识别点
    ("shinobu", "帆坂 忍", 142, 5.5, "#F5C93F", "雨衣尖帽"),
    ("akari", "天野 灯莉", 156, 6.8, "#E8703A", "半纏 + 呆毛"),
    ("sumi", "墨", 178, 7.5, "#23222A", "猫耳 + 尾巴"),
    ("sae", "时雨 冴", 171, 7.8, "#D8DCE4", "高马尾 + 大衣"),
]


def proportions_svg() -> str:
    width, height = 900, 620
    base_y = 500          # 地面线
    top_y = 90            # 最高角色的头顶
    tallest = max(f[2] for f in FIGURES)
    scale = (base_y - top_y) / tallest   # px per cm
    col_w = (width - 230) / len(FIGURES)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="头身比对照图">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
        f'<text x="40" y="46" font-family="{FONT}" font-size="22" font-weight="700" '
        f'fill="{INK}">头身比对照 / PROPORTION CHART</text>',
        f'<text x="40" y="68" font-family="{FONT}" font-size="12" fill="{MUTED}">'
        f'刻度为 10 cm 一格。图形为比例参考用示意剪影，非最终设定稿。</text>',
    ]

    # 高度刻度
    for cm in range(0, tallest + 20, 20):
        y = base_y - cm * scale
        if y < top_y - 20:
            continue
        out.append(
            f'<line x1="88" y1="{y:.1f}" x2="{width - 40}" y2="{y:.1f}" '
            f'stroke="{RULE}" stroke-width="1" stroke-dasharray="3 5"/>'
        )
        out.append(
            f'<text x="80" y="{y + 4:.1f}" text-anchor="end" font-family="{FONT}" '
            f'font-size="11" fill="{MUTED}">{cm}</text>'
        )

    out.append(
        f'<line x1="88" y1="{base_y}" x2="{width - 40}" y2="{base_y}" '
        f'stroke="{INK}" stroke-width="2"/>'
    )

    for idx, (cid, name, cm, heads, color, silhouette) in enumerate(FIGURES):
        cx = 190 + idx * col_w
        total = cm * scale
        head_h = total / heads          # 一"头"的长度
        top = base_y - total
        head_rx = head_h * 0.38
        head_ry = head_h * 0.5          # 头高恰为一个头身单位
        head_cy = top + head_ry

        # 头身分割刻度：第 1 格线正好落在下巴
        h = 1
        while h * head_h < total + 0.5:
            y = top + h * head_h
            out.append(
                f'<line x1="{cx - 52:.1f}" y1="{y:.1f}" x2="{cx + 52:.1f}" y2="{y:.1f}" '
                f'stroke="{MUTED}" stroke-width="0.7" opacity="0.55"/>'
            )
            out.append(
                f'<text x="{cx - 58:.1f}" y="{y + 3:.1f}" text-anchor="end" '
                f'font-family="{FONT}" font-size="9" fill="{MUTED}" opacity="0.75">{h}</text>'
            )
            h += 1

        # 示意剪影：头 + 颈 + 躯干（梯形）+ 双腿
        child = heads < 6.5
        neck_w = head_rx * 0.5
        chin_y = head_cy + head_ry
        shoulder_y = chin_y + head_h * 0.22
        shoulder_w = head_rx * (2.3 if not child else 2.0)
        hip_w = head_rx * (1.55 if not child else 1.7)
        hip_y = base_y - total * (0.50 if not child else 0.44)
        leg_w = hip_w * 0.38

        out.append(
            f'<rect x="{cx - neck_w / 2:.1f}" y="{chin_y - 1:.1f}" width="{neck_w:.1f}" '
            f'height="{shoulder_y - chin_y + 2:.1f}" fill="{color}" '
            f'stroke="{INK}" stroke-width="1.5"/>'
        )
        out.append(
            f'<path d="M {cx - shoulder_w / 2:.1f} {shoulder_y:.1f} '
            f'L {cx + shoulder_w / 2:.1f} {shoulder_y:.1f} '
            f'L {cx + hip_w / 2:.1f} {hip_y:.1f} '
            f'L {cx - hip_w / 2:.1f} {hip_y:.1f} Z" '
            f'fill="{color}" stroke="{INK}" stroke-width="1.5" stroke-linejoin="round"/>'
        )
        for sign in (-1, 1):
            lx = cx + sign * hip_w * 0.24 - leg_w / 2
            out.append(
                f'<rect x="{lx:.1f}" y="{hip_y - 4:.1f}" width="{leg_w:.1f}" '
                f'height="{base_y - hip_y + 4:.1f}" rx="{leg_w / 2:.1f}" '
                f'fill="{color}" stroke="{INK}" stroke-width="1.5"/>'
            )
        out.append(
            f'<ellipse cx="{cx:.1f}" cy="{head_cy:.1f}" rx="{head_rx:.1f}" '
            f'ry="{head_ry:.1f}" fill="{color}" stroke="{INK}" stroke-width="1.5"/>'
        )

        out.append(
            f'<text x="{cx:.1f}" y="{base_y + 24}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="14" font-weight="700" fill="{INK}">{name}</text>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{base_y + 44}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="12" fill="{MUTED}">{cm} cm · {heads} 头身</text>'
        )
        out.append(
            f'<text x="{cx:.1f}" y="{base_y + 64}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="11" fill="{MUTED}">剪影：{silhouette}</text>'
        )

    out.append("</svg>")
    return "\n".join(out)


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    PALETTE_DIR.mkdir(parents=True, exist_ok=True)
    for cid, data in spec.items():
        path = PALETTE_DIR / f"{cid}.svg"
        path.write_text(palette_svg(data), encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")

    prop = ROOT / "assets" / "proportions.svg"
    prop.write_text(proportions_svg(), encoding="utf-8")
    print(f"wrote {prop.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
