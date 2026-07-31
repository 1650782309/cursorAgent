#!/usr/bin/env python3
"""扫描出图目录，读出 PNG 里的生成参数，建立可检索索引。

解决概念阶段最常见的事故：上周那张图特别好，但再也生成不出来了。
ComfyUI 会把完整的 API 工作流写进 PNG 的文本块，这里把它解析成扁平字段。

用法：

  # 建索引
  python scripts/index_outputs.py --root /path/to/ComfyUI/output/pass1

  # 建索引并按底模分组建软链接，方便并排评审
  python scripts/index_outputs.py --root ... --group-by checkpoint --link-dir review

  # 找出某个 seed 的图
  python scripts/index_outputs.py --root ... --filter seed=1234567
"""

from __future__ import annotations

import argparse
import csv
import json
import zlib
from pathlib import Path
from typing import Any

TEXT_KEYS = ("prompt", "workflow", "parameters")
SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced")
MODEL_KEYS = ("ckpt_name", "unet_name", "vae_name", "control_net_name")


def read_png_text(path: Path) -> dict[str, str]:
    """解析 PNG 的 tEXt / zTXt / iTXt 文本块，只用标准库。"""
    out: dict[str, str] = {}
    with path.open("rb") as fh:
        if fh.read(8) != b"\x89PNG\r\n\x1a\n":
            return out
        while True:
            head = fh.read(8)
            if len(head) < 8:
                break
            length = int.from_bytes(head[:4], "big")
            ctype = head[4:8]
            if ctype == b"IEND":
                break
            if ctype == b"IDAT":
                fh.seek(length + 4, 1)
                continue
            data = fh.read(length)
            fh.seek(4, 1)  # 跳过 CRC
            try:
                if ctype == b"tEXt":
                    key, _, value = data.partition(b"\x00")
                    out[key.decode("latin-1")] = value.decode("utf-8", "replace")
                elif ctype == b"zTXt":
                    key, _, rest = data.partition(b"\x00")
                    out[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode(
                        "utf-8", "replace"
                    )
                elif ctype == b"iTXt":
                    key, _, rest = data.partition(b"\x00")
                    compressed = rest[:1] == b"\x01"
                    rest = rest[2:]
                    _, _, rest = rest.partition(b"\x00")  # 语言标签
                    _, _, text = rest.partition(b"\x00")  # 翻译后的关键字
                    if compressed:
                        text = zlib.decompress(text)
                    out[key.decode("latin-1")] = text.decode("utf-8", "replace")
            except (zlib.error, UnicodeDecodeError):
                continue
    return out


def flatten(meta: dict[str, str], path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "file": str(path),
        "name": path.name,
        "size": path.stat().st_size,
    }

    workflow: dict[str, Any] | None = None
    if "prompt" in meta:
        try:
            workflow = json.loads(meta["prompt"])
        except json.JSONDecodeError:
            workflow = None

    if not isinstance(workflow, dict):
        record["parsed"] = False
        return record

    record["parsed"] = True
    titled: dict[str, dict[str, Any]] = {}
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        title = (node.get("_meta") or {}).get("title")
        if title:
            titled[title] = node

        inputs = node.get("inputs", {})
        for key in MODEL_KEYS:
            value = inputs.get(key)
            if isinstance(value, str):
                record.setdefault(key.replace("ckpt_name", "checkpoint"), value)

        if node.get("class_type") in SAMPLER_CLASSES:
            for key in ("seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
                if key in inputs and not isinstance(inputs[key], list):
                    record.setdefault("seed" if key == "noise_seed" else key, inputs[key])

        if node.get("class_type") == "LoraLoader":
            record.setdefault("loras", []).append(
                {
                    "name": inputs.get("lora_name"),
                    "model": inputs.get("strength_model"),
                    "clip": inputs.get("strength_clip"),
                }
            )

    positive = titled.get("POSITIVE")
    negative = titled.get("NEGATIVE")
    if positive is None:
        encoders = [
            n for n in workflow.values()
            if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"
        ]
        positive = encoders[0] if encoders else None
    if positive:
        record["positive"] = positive.get("inputs", {}).get("text")
    if negative:
        record["negative"] = negative.get("inputs", {}).get("text")

    return record


def matches(record: dict[str, Any], filters: list[tuple[str, str]]) -> bool:
    for key, expected in filters:
        actual = record.get(key)
        if actual is None:
            return False
        if expected.lower() not in str(actual).lower():
            return False
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="出图索引",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--root", required=True, type=Path, help="出图根目录，会递归扫描")
    p.add_argument("--out", type=Path, default=None, help="索引输出目录，默认为 --root")
    p.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="field=value",
        help="按字段过滤，可重复；子串匹配不区分大小写",
    )
    p.add_argument("--group-by", default=None, help="按字段分组建软链接，例如 checkpoint")
    p.add_argument("--link-dir", type=Path, default=None, help="软链接输出目录")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root: Path = args.root
    if not root.is_dir():
        raise SystemExit(f"目录不存在: {root}")

    filters = []
    for item in args.filter:
        if "=" not in item:
            raise SystemExit(f"--filter 格式应为 field=value，收到: {item}")
        key, value = item.split("=", 1)
        filters.append((key, value))

    records: list[dict[str, Any]] = []
    unparsed = 0
    for path in sorted(root.rglob("*.png")):
        record = flatten(read_png_text(path), path)
        if not record.get("parsed"):
            unparsed += 1
        if matches(record, filters):
            records.append(record)

    out_dir = args.out or root
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "index.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    csv_fields = [
        "name", "checkpoint", "unet_name", "seed", "steps", "cfg",
        "sampler_name", "scheduler", "denoise", "positive", "file",
    ]
    csv_path = out_dir / "index.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)

    print(f"[索引] {len(records)} 张图 -> {jsonl_path}")
    print(f"[表格] {csv_path}（Excel 可直接打开）")
    if unparsed:
        print(f"[提示] {unparsed} 张图没有可解析的生成参数，可能不是 ComfyUI 直接产出的")

    if args.group_by:
        link_root = args.link_dir or (out_dir / "grouped")
        created = 0
        for record in records:
            key = str(record.get(args.group_by) or "unknown")
            safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in key)[:60]
            target = link_root / safe
            target.mkdir(parents=True, exist_ok=True)
            link = target / record["name"]
            if link.exists() or link.is_symlink():
                continue
            try:
                link.symlink_to(Path(record["file"]).resolve())
                created += 1
            except OSError as exc:
                print(f"[软链接失败] {link}: {exc}")
                break
        print(f"[分组] 按 {args.group_by} 建了 {created} 个软链接 -> {link_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
