#!/usr/bin/env python3
"""渲染 Spine 工作流的演示图，用于 PR、周会和验收。

产出四张图，回答四个不同的问题：

``01_wardrobe``   每个角色的全部换装摆在一起 —— 这套流程到底产出了什么
``02_walk``       走路循环的动图 —— 换装后动起来会不会穿帮
``03_atlas``      attachment 贴图的换装前后 —— 改的是贴图还是只是渲染滤镜
``04_pipeline``   一个姿势的四张中间图 —— SD 到底看到了什么

用法：先跑完 build 与各套 reskin，再执行

    python3 tools/gen_spine_demo.py [输出目录]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from spineforge import pipeline, raster
from spineforge.concept import Concept, list_concepts
from spineforge.config import Config

# 按头身比从小到大排，一眼能看出设定集的头身比确实驱动了骨架
ORDER = ["shinobu", "akari", "sae", "sumi", "icarus"]
ROMAJI = {"shinobu": "Shinobu", "akari": "Akari", "sae": "Sae",
          "sumi": "Sumi", "icarus": "Icarus"}

GREY = (110, 110, 110)
LINE = (205, 205, 205)


def skin_dirs(cfg: Config, concept: Concept) -> list[tuple[str, Path]]:
    """``[(标签, 贴图目录)]``，第一项是设定集原色。"""
    out = [("bible", cfg.images_dir(concept.id))]
    for name in concept.outfits:
        path = cfg.skin_dir(concept.id, name, 0) / "images"
        if path.is_dir():
            out.append((name, path))
    return out


def render(concept: Concept, sk, textures, anim: str | None, phase: float,
           scale: int) -> Image.Image:
    sk.pose(anim, sk.duration(anim) * phase if anim else 0.0)
    img = pipeline.on_white(
        raster.render_color(sk, textures, concept.canvas.width, concept.canvas.height)
    )
    return img.resize((img.width // scale, img.height // scale), Image.LANCZOS)


def wardrobe(cfg: Config, concepts: dict[str, Concept], out: Path) -> Path:
    """每行一个角色：设定集原色 + 该角色的全部换装。"""
    scale = 4
    label_w, header_h = 118, 30
    cells: list[tuple[Concept, list[tuple[str, Image.Image]]]] = []
    for cid in ORDER:
        concept = concepts[cid]
        sk = pipeline.load_skeleton(concept, cfg)
        row = []
        for name, images in skin_dirs(cfg, concept):
            textures = pipeline.load_textures(images)
            row.append((name, render(concept, sk, textures, "idle", 0.3, scale)))
        cells.append((concept, row))

    cols = max(len(r) for _, r in cells)
    tw = max(im.width for _, r in cells for _, im in r)
    th = max(im.height for _, r in cells for _, im in r)

    sheet = Image.new("RGB", (label_w + cols * tw, header_h + len(cells) * th), "white")
    d = ImageDraw.Draw(sheet)
    d.text((10, 10), "character", fill="black")
    d.text((label_w + 8, 10), "bible palette", fill="black")
    d.text((label_w + tw + 8, 10), "SD reskin per outfit (mock backend)", fill="black")
    d.line([(label_w + tw, 0), (label_w + tw, sheet.height)], fill=LINE, width=2)

    for r, (concept, row) in enumerate(cells):
        top = header_h + r * th
        d.text((10, top + th // 2 - 14), ROMAJI[concept.id], fill="black")
        d.text((10, top + th // 2 - 1),
               f"{concept.bible.height_cm:.0f}cm", fill=GREY)
        d.text((10, top + th // 2 + 11),
               f"{concept.bible.heads} heads", fill=GREY)
        for i, (name, img) in enumerate(row):
            x = label_w + i * tw
            sheet.paste(img, (x + (tw - img.width) // 2, top + (th - img.height)))
            d.text((x + 6, top + 4), name, fill=GREY)
        if r:
            d.line([(0, top), (sheet.width, top)], fill=(238, 238, 238), width=1)

    path = out / "01_wardrobe.png"
    sheet.save(path)
    return path


def walk_cycle(cfg: Config, concepts: dict[str, Concept], out: Path,
               frames: int = 16) -> Path:
    """走路循环动图，排布与衣柜图一致：一行一个角色，行内是各套换装。"""
    scale = 5
    label_w, header_h = 100, 24
    loaded = []
    for cid in ORDER:
        concept = concepts[cid]
        sk = pipeline.load_skeleton(concept, cfg)
        variants = [(n, pipeline.load_textures(p)) for n, p in skin_dirs(cfg, concept)]
        loaded.append((concept, sk, variants))

    cols = max(len(v) for _, _, v in loaded)
    tw = max(c.canvas.width for c, _, _ in loaded) // scale
    th = max(c.canvas.height for c, _, _ in loaded) // scale
    size = (label_w + cols * tw, header_h + len(loaded) * th)

    # 文字与分隔线每帧都一样，先画在底板上，逐帧只贴角色
    board = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(board)
    d.text((8, 7), "walk cycle", fill="black")
    d.text((label_w + 6, 7), "bible", fill=GREY)
    d.text((label_w + tw + 6, 7), "SD reskin per outfit", fill=GREY)
    d.line([(label_w + tw, 0), (label_w + tw, size[1])], fill=LINE, width=2)
    for r, (concept, _, _) in enumerate(loaded):
        top = header_h + r * th
        d.text((8, top + th // 2 - 6), ROMAJI[concept.id], fill="black")
        if r:
            d.line([(0, top), (size[0], top)], fill=(238, 238, 238), width=1)

    pages: list[Image.Image] = []
    for f in range(frames):
        page = board.copy()
        for r, (concept, sk, variants) in enumerate(loaded):
            top = header_h + r * th
            for i, (_, textures) in enumerate(variants):
                img = render(concept, sk, textures, "walk", f / frames, scale)
                page.paste(img, (label_w + i * tw + (tw - img.width) // 2,
                                 top + th - img.height))
        pages.append(page)

    path = out / "02_walk.gif"
    pages[0].save(path, save_all=True, append_images=pages[1:],
                  duration=1000 // 12, loop=0, optimize=False)
    return path


def atlas(cfg: Config, concepts: dict[str, Concept], out: Path,
          cid: str = "sae", parts: tuple[str, ...] = (
              "coat_body", "coat_skirt", "coat_sleeve_l", "L_trouser", "L_boot_shaft",
          )) -> Path:
    """同一批 attachment 贴图在换装前后的样子。

    换装改的是贴图本身而不是渲染时的滤镜，这张图就是证据：
    每一列是一张独立的 PNG，直接可以拖进 Spine 编辑器。
    """
    concept = concepts[cid]
    rows = skin_dirs(cfg, concept)
    tiles: list[tuple[str, list[Image.Image]]] = []
    for name, images in rows:
        row = []
        for part in parts:
            src = Image.open(images / f"{part}.png").convert("RGBA")
            # 洋红衬底，好看清 alpha 边界
            bg = Image.new("RGBA", src.size, (255, 0, 255, 255))
            row.append(Image.alpha_composite(bg, src).convert("RGB"))
        tiles.append((name, row))

    label_w, header_h, gap = 118, 46, 10
    widths = [max(max(t[1][i].width for t in tiles), 74) for i in range(len(parts))]
    th = max(im.height for _, r in tiles for im in r)
    sheet = Image.new("RGB", (label_w + sum(widths) + gap * len(parts),
                              header_h + len(tiles) * (th + gap)), "white")
    d = ImageDraw.Draw(sheet)
    d.text((10, 8), f"{ROMAJI[cid]} - attachment textures (magenta = alpha 0)",
           fill="black")

    x = label_w
    for i, part in enumerate(parts):
        d.text((x, 28), part, fill=GREY)
        x += widths[i] + gap

    for r, (name, row) in enumerate(tiles):
        top = header_h + r * (th + gap)
        d.text((10, top + th // 2), name, fill="black" if r == 0 else GREY)
        x = label_w
        for i, img in enumerate(row):
            sheet.paste(img, (x, top))
            x += widths[i] + gap

    path = out / "03_atlas.png"
    sheet.save(path)
    return path


def pipeline_steps(cfg: Config, concepts: dict[str, Concept], out: Path,
                   cid: str = "akari", outfit: str = "field_work") -> Path | None:
    """一个姿势的四张中间图：底图 / 遮罩 / 控制图 / 重绘结果。"""
    steps = cfg.skin_dir(cid, outfit, 0) / "steps"
    if not steps.is_dir():
        return None

    kinds = ["base", "mask", "canny", "redraw"]
    picked = sorted(steps.glob("*_base.png"))[:3]
    if not picked:
        return None

    scale = 3
    rows = []
    for base in picked:
        stem = base.name[:-len("_base.png")]
        row = []
        for kind in kinds:
            img = Image.open(steps / f"{stem}_{kind}.png").convert("RGB")
            row.append(img.resize((img.width // scale, img.height // scale),
                                  Image.LANCZOS))
        rows.append((stem, row))

    label_w, header_h = 150, 46
    tw = max(im.width for _, r in rows for im in r)
    th = max(im.height for _, r in rows for im in r)
    sheet = Image.new("RGB", (label_w + len(kinds) * tw, header_h + len(rows) * th),
                      "white")
    d = ImageDraw.Draw(sheet)
    d.text((10, 8), f"{ROMAJI[cid]} / {outfit} - per-pose redraw", fill="black")
    titles = ["1 base image", "2 inpaint mask", "3 ControlNet edges", "4 SD output"]
    for i, title in enumerate(titles):
        d.text((label_w + i * tw + 6, 28), title, fill=GREY)
    for r, (stem, row) in enumerate(rows):
        top = header_h + r * th
        d.text((10, top + th // 2), stem, fill="black")
        for i, img in enumerate(row):
            sheet.paste(img, (label_w + i * tw, top))

    path = out / "04_pipeline.png"
    sheet.save(path)
    return path


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("build/demo")
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    concepts = {c.id: c for c in list_concepts(cfg)}
    missing = [cid for cid in ORDER if cid not in concepts]
    if missing:
        print(f"概念库里缺少 {missing}", file=sys.stderr)
        return 1

    for fn in (wardrobe, walk_cycle, atlas, pipeline_steps):
        path = fn(cfg, concepts, out)
        print(f"{fn.__name__:<15} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
