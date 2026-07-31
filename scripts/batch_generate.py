#!/usr/bin/env python3
"""概念发散批量出图。

把词库模板展开成大量提示词，注入 ComfyUI API 工作流并排队执行，
同时把每一张图的 seed、提示词、抽到的词库条目写进 manifest，
保证任何一张好图都能复现。

两种模式：

  随机模式  --count N
      每次所有维度随机，用于第一阶段大范围铺量。

  网格模式  --axis <词库名> [--axis <词库名> ...]
      对指定词库做笛卡尔积穷举，其余维度随机；
      配合 --fixed-seed 固定随机数种子，就成为严格的控制变量比对。

示例：

  # 铺 300 张全身发散
  python scripts/batch_generate.py --count 300 --label pass1

  # 锁姿势 + 扫材质，严格可比
  python scripts/batch_generate.py \
      --workflow workflows/api/02_pose_locked_compare.json \
      --template prompts/templates/compare_locked.txt \
      --axis outfit/material --fixed-seed 20260731 --label mat-scan

  # 只看展开结果，不出图
  python scripts/batch_generate.py --count 5 --dry-run
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import random
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comfy_client import ComfyClient, ComfyError  # noqa: E402
from wildcard import WildcardError, WildcardResolver, load_template  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SAFE_TAG_RE = re.compile(r"[^a-z0-9]+")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="概念发散批量出图",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--workflow",
        default=REPO_ROOT / "workflows/api/01_divergence_sdxl.json",
        type=Path,
        help="ComfyUI API 格式工作流",
    )
    p.add_argument(
        "--template",
        default=REPO_ROOT / "prompts/templates/divergence_fullbody.txt",
        type=Path,
        help="正面提示词模板",
    )
    p.add_argument(
        "--negative",
        default=REPO_ROOT / "prompts/negative_anime.txt",
        type=Path,
        help="负面提示词文件，传 none 表示不注入",
    )
    p.add_argument("--wildcards", default=REPO_ROOT / "wildcards", type=Path)
    p.add_argument("--count", type=int, default=20, help="随机模式的出图数量")
    p.add_argument(
        "--axis",
        action="append",
        default=[],
        metavar="词库名",
        help="网格模式的扫描轴，可重复；例如 --axis design/silhouette",
    )
    p.add_argument("--repeat", type=int, default=1, help="网格模式下每格重复次数")
    p.add_argument("--limit", type=int, default=0, help="网格总数上限，0 为不限")
    p.add_argument("--seed", type=int, default=None, help="控制词库抽取的随机数种子")
    p.add_argument(
        "--fixed-seed",
        type=int,
        default=None,
        help="把采样器 seed 固定为该值，做控制变量比对时必须用",
    )
    p.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="TITLE.input=value",
        help="覆盖工作流节点参数，例如 --set LATENT.width=768",
    )
    p.add_argument("--label", default="run", help="本批次标签，用于输出目录命名")
    p.add_argument("--server", default="127.0.0.1:8188")
    p.add_argument("--out", default=REPO_ROOT / "runs", type=Path, help="manifest 输出目录")
    p.add_argument("--download", action="store_true", help="把出图下载到本批次目录")
    p.add_argument(
        "--queue-ahead",
        type=int,
        default=3,
        help="最多同时排队的任务数，让 GPU 不空转",
    )
    p.add_argument("--job-timeout", type=float, default=900.0)
    p.add_argument("--dry-run", action="store_true", help="只展开提示词，不提交")
    return p.parse_args(argv)


def safe_tag(value: str, max_len: int = 40) -> str:
    tag = SAFE_TAG_RE.sub("-", value.lower()).strip("-")
    return tag[:max_len] or "x"


def find_node(workflow: dict[str, Any], title: str) -> str | None:
    for node_id, node in workflow.items():
        if (node.get("_meta") or {}).get("title") == title:
            return node_id
    return None


def coerce(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def parse_overrides(items: list[str]) -> list[tuple[str, str, Any]]:
    parsed: list[tuple[str, str, Any]] = []
    for item in items:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise SystemExit(f"--set 格式应为 TITLE.input=value，收到: {item}")
        target, raw = item.split("=", 1)
        title, key = target.split(".", 1)
        parsed.append((title, key, coerce(raw)))
    return parsed


def apply_override(workflow: dict[str, Any], title: str, key: str, value: Any) -> None:
    node_id = find_node(workflow, title)
    if node_id is None:
        raise SystemExit(f"工作流里找不到标题为 {title} 的节点")
    workflow[node_id]["inputs"][key] = value


def build_jobs(
    resolver: WildcardResolver,
    template: str,
    args: argparse.Namespace,
    rng: random.Random,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    if args.axis:
        axis_values = [resolver.entries(name) for name in args.axis]
        combos = list(itertools.product(*axis_values))
        if args.limit:
            combos = combos[: args.limit]
        for combo in combos:
            overrides = dict(zip(args.axis, combo))
            for _ in range(max(1, args.repeat)):
                prompt, picks = resolver.resolve(template, overrides)
                jobs.append({"prompt": prompt, "picks": picks, "axis": overrides})
    else:
        for _ in range(max(1, args.count)):
            prompt, picks = resolver.resolve(template)
            jobs.append({"prompt": prompt, "picks": picks, "axis": {}})

    for index, job in enumerate(jobs):
        job["index"] = index
        job["seed"] = args.fixed_seed if args.fixed_seed is not None else rng.randrange(2**31)
        job["subfolder"] = "/".join(
            [args.label] + [safe_tag(v) for v in job["axis"].values()]
        )

    return jobs


def prepare_workflow(
    base: dict[str, Any],
    job: dict[str, Any],
    negative: str | None,
    overrides: list[tuple[str, str, Any]],
) -> dict[str, Any]:
    workflow = copy.deepcopy(base)

    positive_id = find_node(workflow, "POSITIVE")
    if positive_id is None:
        raise SystemExit("工作流缺少标题为 POSITIVE 的 CLIPTextEncode 节点")
    workflow[positive_id]["inputs"]["text"] = job["prompt"]

    negative_id = find_node(workflow, "NEGATIVE")
    if negative_id is not None and negative:
        workflow[negative_id]["inputs"]["text"] = negative

    sampler_id = find_node(workflow, "SAMPLER")
    if sampler_id is None:
        raise SystemExit("工作流缺少标题为 SAMPLER 的采样节点")
    workflow[sampler_id]["inputs"]["seed"] = job["seed"]

    save_id = find_node(workflow, "SAVE")
    if save_id is not None:
        workflow[save_id]["inputs"]["filename_prefix"] = f"{job['subfolder']}/img"

    for title, key, value in overrides:
        apply_override(workflow, title, key, value)

    return workflow


def describe_models(workflow: dict[str, Any]) -> dict[str, Any]:
    """从工作流里抽出模型信息，写进 manifest 便于复现。"""
    models: dict[str, Any] = {}
    for node in workflow.values():
        inputs = node.get("inputs", {})
        for key in ("ckpt_name", "unet_name", "vae_name", "lora_name", "control_net_name"):
            if key in inputs and isinstance(inputs[key], str):
                models.setdefault(key, inputs[key])
    return models


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        template = load_template(args.template)
    except OSError as exc:
        raise SystemExit(f"读不到模板 {args.template}: {exc}") from exc

    negative: str | None = None
    if str(args.negative).lower() != "none":
        negative = load_template(args.negative)

    base_workflow = json.loads(Path(args.workflow).read_text(encoding="utf-8"))
    overrides = parse_overrides(args.set)

    seed = args.seed if args.seed is not None else int(time.time())
    rng = random.Random(seed)
    resolver = WildcardResolver(args.wildcards, rng)

    try:
        jobs = build_jobs(resolver, template, args, rng)
    except WildcardError as exc:
        raise SystemExit(f"词库展开失败: {exc}") from exc

    if not jobs:
        raise SystemExit("没有生成任何任务")

    print(f"[计划] {len(jobs)} 个任务  词库随机种子={seed}  工作流={args.workflow.name}")
    if args.axis:
        print(f"[网格] 扫描轴: {', '.join(args.axis)}")
    if args.fixed_seed is not None:
        print(f"[控制] 采样 seed 固定为 {args.fixed_seed}")

    if args.dry_run:
        for job in jobs:
            axis = "  ".join(f"{k}={v}" for k, v in job["axis"].items())
            print(f"\n--- #{job['index']:04d} seed={job['seed']} {axis}")
            print(job["prompt"])
        print(f"\n[dry-run] 共 {len(jobs)} 个任务，未提交。")
        return 0

    run_dir = args.out / f"{datetime.now():%Y%m%d-%H%M%S}-{safe_tag(args.label)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.jsonl"
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "label": args.label,
                "workflow": str(args.workflow),
                "template": str(args.template),
                "negative_file": None if negative is None else str(args.negative),
                "wildcard_seed": seed,
                "fixed_sampler_seed": args.fixed_seed,
                "axes": args.axis,
                "job_count": len(jobs),
                "node_overrides": [f"{t}.{k}={v}" for t, k, v in overrides],
                "models": describe_models(base_workflow),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[输出] {run_dir}")

    client = ComfyClient(args.server)
    try:
        client.ping()
    except ComfyError as exc:
        raise SystemExit(f"{exc}\n请先启动 ComfyUI，或用 --server 指定地址。") from exc

    client_id = str(uuid.uuid4())
    pending: list[tuple[str, dict[str, Any]]] = []
    queue = list(jobs)
    done = 0
    failed = 0
    started = time.monotonic()

    def drain(target: int) -> None:
        nonlocal done, failed
        while len(pending) > target:
            prompt_id, job = pending.pop(0)
            record = {
                "index": job["index"],
                "seed": job["seed"],
                "prompt": job["prompt"],
                "negative": negative,
                "axis": job["axis"],
                "picks": job["picks"],
                "subfolder": job["subfolder"],
                "prompt_id": prompt_id,
            }
            try:
                entry = client.wait(prompt_id, timeout=args.job_timeout)
                images = ComfyClient.collect_images(entry)
                record["images"] = images
                if args.download:
                    record["local"] = [
                        str(client.download(img, run_dir / "images").relative_to(run_dir))
                        for img in images
                    ]
                done += 1
            except ComfyError as exc:
                record["error"] = str(exc)
                failed += 1
                print(f"[失败] #{job['index']:04d} {exc}")
            with manifest_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            total = done + failed
            if total % 10 == 0 or total == len(jobs):
                elapsed = time.monotonic() - started
                print(
                    f"[进度] {total}/{len(jobs)}  成功 {done}  失败 {failed}  "
                    f"用时 {elapsed:.0f}s"
                )

    try:
        while queue:
            job = queue.pop(0)
            workflow = prepare_workflow(base_workflow, job, negative, overrides)
            try:
                prompt_id = client.submit(workflow, client_id)
            except ComfyError as exc:
                failed += 1
                print(f"[提交失败] #{job['index']:04d} {exc}")
                continue
            pending.append((prompt_id, job))
            drain(max(0, args.queue_ahead - 1))
        drain(0)
    except KeyboardInterrupt:
        print("\n[中断] 已提交的任务仍会在 ComfyUI 队列里执行，manifest 记录到此为止。")
        return 130

    print(f"[完成] 成功 {done}  失败 {failed}  manifest: {manifest_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
