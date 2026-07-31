#!/usr/bin/env python3
"""角色 LoRA 数据集体检与标签整理。

角色 LoRA 训不好，九成问题出在数据和打标上，而不是超参。
这个脚本把最容易翻车的几项先查出来，再按打标原则批量修标签。

体检（默认只读，不改文件）：

  python scripts/prepare_dataset.py --dir datasets/char_xxx/images

  会报告：缺标签的图、重复图（按内容哈希）、分辨率与长宽比分布、
  视角覆盖度、标签词频，以及两类需要人工决策的标签：
    - 出现率过高的标签：通常是角色固有特征，应当删掉让它并入触发词
    - 只出现一两次的标签：多半是自动打标的噪声，建议清理

整理（加 --apply 才会写盘，原文件会留 .bak）：

  python scripts/prepare_dataset.py --dir datasets/char_xxx/images \\
      --trigger chartrigger \\
      --drop "silver hair,amber eyes,long hair" \\
      --apply

打标原则见 docs/05-lora.md：角色固有特征不入标签，可变要素必须入标签。
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from collections import Counter, defaultdict
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

# 视角覆盖度检查用的关键词。角色 LoRA 最常见的失败是训练集全是同一个角度，
# 换视角就崩，所以这里单独统计。
VIEW_KEYWORDS = {
    "正面": ("front view", "facing viewer", "straight on"),
    "侧面": ("side view", "from side", "profile"),
    "背面": ("back view", "from behind"),
    "俯视": ("from above",),
    "仰视": ("from below",),
    "全身": ("full body",),
    "半身": ("upper body", "cowboy shot"),
    "特写": ("portrait", "close-up", "face focus"),
}


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    index = 2
    sof_markers = set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0))
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in sof_markers:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        index += 2 + length
    return None


def webp_size(data: bytes) -> tuple[int, int] | None:
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 ":
        # 有损帧头：3 字节 frame tag + 3 字节起始码，之后是 14 位宽高
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    return None


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.open("rb").read(65536)
    except OSError:
        return None
    for reader in (png_size, jpeg_size, webp_size):
        try:
            size = reader(data)
        except (struct.error, IndexError):
            size = None
        if size:
            return size
    return None


def read_tags(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [t.strip() for t in path.read_text(encoding="utf-8").split(",") if t.strip()]


def write_tags(path: Path, tags: list[str]) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    if path.is_file() and not backup.is_file():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(", ".join(tags) + "\n", encoding="utf-8")


def bucket_of(width: int, height: int) -> str:
    """粗略归类到 SDXL 常用桶，用来看数据的长宽比是否过于集中。"""
    ratio = width / height
    if ratio < 0.6:
        return "极竖 (<0.60)"
    if ratio < 0.78:
        return "竖构图 832x1216 附近"
    if ratio < 0.95:
        return "略竖 896x1152 附近"
    if ratio <= 1.05:
        return "方图 1024x1024"
    if ratio <= 1.3:
        return "略横 1152x896 附近"
    if ratio <= 1.7:
        return "横构图 1216x832 附近"
    return "极横 (>1.70)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="角色 LoRA 数据集体检与标签整理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dir", required=True, type=Path, help="训练图目录（图与同名 .txt 标签同级）")
    p.add_argument("--trigger", default=None, help="触发词，会被移到标签首位")
    p.add_argument("--drop", default="", help="要删除的标签，逗号分隔；子串精确匹配整个标签")
    p.add_argument("--top", type=int, default=30, help="词频报告显示条数")
    p.add_argument(
        "--high-freq",
        type=float,
        default=0.85,
        help="出现率高于该比例的标签视为角色固有特征候选",
    )
    p.add_argument("--min-side", type=int, default=768, help="低于该短边的图会被标为偏小")
    p.add_argument("--apply", action="store_true", help="真正写入标签改动")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root: Path = args.dir
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    images = sorted(p for p in root.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        raise SystemExit(f"{root} 里没有找到图片（支持 {', '.join(sorted(IMAGE_SUFFIXES))}）")

    print(f"数据集: {root}")
    print(f"图片数: {len(images)}\n")

    missing_caption: list[str] = []
    empty_caption: list[str] = []
    small_images: list[str] = []
    unknown_size: list[str] = []
    digests: defaultdict[str, list[str]] = defaultdict(list)
    buckets: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    view_hits: Counter[str] = Counter()
    tags_by_image: dict[Path, list[str]] = {}

    for image in images:
        caption_path = image.with_suffix(".txt")
        tags = read_tags(caption_path)
        tags_by_image[caption_path] = tags
        if not caption_path.is_file():
            missing_caption.append(image.name)
        elif not tags:
            empty_caption.append(image.name)
        tag_counter.update(tags)

        joined = ", ".join(tags).lower()
        for label, keywords in VIEW_KEYWORDS.items():
            if any(k in joined for k in keywords):
                view_hits[label] += 1

        size = image_size(image)
        if size is None:
            unknown_size.append(image.name)
        else:
            width, height = size
            buckets[bucket_of(width, height)] += 1
            if min(width, height) < args.min_side:
                small_images.append(f"{image.name} ({width}x{height})")

        digests[hashlib.md5(image.read_bytes()).hexdigest()].append(image.name)

    print("== 数据完整性 ==")
    if missing_caption:
        print(f"  缺标签文件 {len(missing_caption)} 张: {', '.join(missing_caption[:8])}"
              f"{' ...' if len(missing_caption) > 8 else ''}")
    if empty_caption:
        print(f"  标签为空 {len(empty_caption)} 张: {', '.join(empty_caption[:8])}")
    duplicates = {d: names for d, names in digests.items() if len(names) > 1}
    if duplicates:
        print(f"  完全重复的图 {len(duplicates)} 组（重复喂同一张图会直接导致过拟合）:")
        for names in list(duplicates.values())[:5]:
            print(f"    {' = '.join(names)}")
    if small_images:
        print(f"  短边小于 {args.min_side} 的图 {len(small_images)} 张（建议剔除，放大等于画质污染）:")
        print(f"    {', '.join(small_images[:6])}")
    if unknown_size:
        print(f"  无法读取尺寸 {len(unknown_size)} 张: {', '.join(unknown_size[:6])}")
    if not (missing_caption or empty_caption or duplicates or small_images or unknown_size):
        print("  未发现问题")

    print("\n== 长宽比分布 ==")
    for bucket, count in buckets.most_common():
        bar = "#" * max(1, round(count / len(images) * 40))
        print(f"  {bucket:<26} {count:>3}  {bar}")
    if buckets and buckets.most_common(1)[0][1] / len(images) > 0.9:
        print("  提示: 长宽比过度集中，模型换构图时容易崩，建议补几张不同画幅的图")

    print("\n== 视角与镜头覆盖度 ==")
    for label in VIEW_KEYWORDS:
        count = view_hits.get(label, 0)
        flag = "  <- 缺失" if count == 0 else ""
        print(f"  {label:<4} {count:>3} 张{flag}")
    print("  说明: 正面/侧面/背面 至少各有 3 张，全身与特写都要有，否则换视角必崩")

    print(f"\n== 标签词频 Top {args.top} ==")
    for tag, count in tag_counter.most_common(args.top):
        print(f"  {count:>3}  {tag}")

    threshold = args.high_freq * len(images)
    high_freq = [t for t, c in tag_counter.items() if c >= threshold]
    rare = [t for t, c in tag_counter.items() if c <= 1]
    print(f"\n== 需要人工决策的标签 ==")
    if high_freq:
        print(f"  出现率 >= {args.high_freq:.0%}，多半是角色固有特征，建议用 --drop 删掉并入触发词:")
        for tag in sorted(high_freq):
            print(f"    {tag}  ({tag_counter[tag]}/{len(images)})")
    if rare:
        print(f"  只出现 1 次，多半是自动打标噪声，建议核对后清理（共 {len(rare)} 个）:")
        print(f"    {', '.join(sorted(rare)[:15])}{' ...' if len(rare) > 15 else ''}")
    if not high_freq and not rare:
        print("  无")

    drop = {t.strip() for t in args.drop.split(",") if t.strip()}
    if not drop and not args.trigger:
        print("\n未指定 --trigger 或 --drop，仅做体检，未改动任何文件。")
        return 0

    changed = 0
    for caption_path, tags in tags_by_image.items():
        new_tags = [t for t in tags if t not in drop]
        if args.trigger:
            new_tags = [t for t in new_tags if t != args.trigger]
            new_tags.insert(0, args.trigger)
        if new_tags == tags:
            continue
        changed += 1
        if args.apply:
            write_tags(caption_path, new_tags)

    print()
    if args.apply:
        print(f"已改写 {changed} 个标签文件，原文件备份为同名 .bak")
    else:
        print(f"将会改写 {changed} 个标签文件（加 --apply 才真正写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
