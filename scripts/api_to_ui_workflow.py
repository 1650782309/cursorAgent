#!/usr/bin/env python3
"""把 API 格式工作流转成 ComfyUI 界面能直接打开的 UI 格式。

仓库里的 workflows/api/*.json 是给脚本用的，界面里打不开。
这个脚本连上本机 ComfyUI 读取真实的节点定义（/object_info），
据此判断哪些参数是控件、哪些是连线，再生成带布局的 UI 工作流。

因为参数顺序取自当前这台机器上的 ComfyUI，所以不会出现
"照着文档写死顺序、换个版本就错位"的问题。

用法：

    # ComfyUI 需要先启动
    python scripts/api_to_ui_workflow.py

    # 指定单个文件与输出目录
    python scripts/api_to_ui_workflow.py --input workflows/api/01_divergence_sdxl.json --out workflows/ui

生成后在浏览器里用 工作流 -> 打开 选择 workflows/ui/*.json 即可。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

WIDGET_PRIMITIVES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# 少数节点默认尺寸太小会挡住文字，这里给几个常用的定制尺寸
NODE_SIZES = {
    "CLIPTextEncode": [400, 200],
    "SaveImage": [320, 340],
    "LoadImage": [320, 340],
    "CheckpointLoaderSimple": [330, 100],
    "ControlNetLoader": [330, 60],
    "UNETLoader": [330, 82],
    "DualCLIPLoader": [330, 106],
    "VAELoader": [330, 60],
    "UpscaleModelLoader": [330, 60],
    "KSampler": [300, 262],
    "ControlNetApplyAdvanced": [320, 166],
}
DEFAULT_SIZE = [280, 106]

COLUMN_WIDTH = 420
ROW_HEIGHT = 400


class ConvertError(RuntimeError):
    pass


def fetch_object_info(server: str) -> dict[str, Any]:
    if not server.startswith(("http://", "https://")):
        server = f"http://{server}"
    url = f"{server.rstrip('/')}/object_info"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise ConvertError(
            f"连不上 ComfyUI ({url}): {exc.reason}\n请先启动 ComfyUI，或用 --server 指定地址。"
        ) from exc


def is_widget(spec: Any) -> bool:
    """判断某个输入在界面里是控件还是连线接口。

    下拉框有两种写法：老写法直接给候选列表，新写法是 ["COMBO", {"options": [...]}]，
    同一个 ComfyUI 版本里两种可能并存，两种都要认。
    """
    if not isinstance(spec, list) or not spec:
        return False
    type_def = spec[0]
    if isinstance(type_def, list):  # 老写法的下拉框
        return True
    return type_def == "COMBO" or type_def in WIDGET_PRIMITIVES


def spec_options(spec: Any) -> dict[str, Any]:
    if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1]
    return {}


def default_value(spec: Any) -> Any:
    options = spec_options(spec)
    if "default" in options:
        return options["default"]
    type_def = spec[0]
    if isinstance(type_def, list):
        return type_def[0] if type_def else ""
    if type_def == "COMBO":
        choices = options.get("options") or []
        return choices[0] if choices else ""
    return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(type_def, None)


def ordered_inputs(schema: dict[str, Any]) -> list[tuple[str, Any, bool]]:
    """按界面顺序返回 (名称, 规格, 是否可选)。"""
    inputs = schema.get("input", {})
    order = schema.get("input_order", {})
    result: list[tuple[str, Any, bool]] = []
    for section, optional in (("required", False), ("optional", True)):
        names = order.get(section) or list((inputs.get(section) or {}).keys())
        for name in names:
            spec = (inputs.get(section) or {}).get(name)
            if spec is None:
                continue
            result.append((name, spec, optional))
    return result


def topological_order(workflow: dict[str, Any]) -> list[str]:
    depth: dict[str, int] = {}

    def resolve(node_id: str, seen: frozenset[str]) -> int:
        if node_id in depth:
            return depth[node_id]
        if node_id in seen:
            raise ConvertError(f"工作流存在环: {node_id}")
        best = 0
        for value in workflow[node_id].get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in workflow:
                best = max(best, resolve(str(value[0]), seen | {node_id}) + 1)
        depth[node_id] = best
        return best

    for node_id in workflow:
        resolve(node_id, frozenset())
    return sorted(workflow, key=lambda n: (depth[n], int(n)))


def convert(workflow: dict[str, Any], object_info: dict[str, Any], name: str) -> dict[str, Any]:
    order = topological_order(workflow)
    depth: dict[str, int] = {}
    for node_id in order:
        parents = [
            str(v[0])
            for v in workflow[node_id].get("inputs", {}).values()
            if isinstance(v, list) and len(v) == 2 and str(v[0]) in workflow
        ]
        depth[node_id] = max((depth[p] + 1 for p in parents), default=0)

    column_counts: dict[int, int] = {}
    nodes: dict[str, dict[str, Any]] = {}
    link_id = 0
    links: list[list[Any]] = []

    for position, node_id in enumerate(order):
        api_node = workflow[node_id]
        class_type = api_node["class_type"]
        schema = object_info.get(class_type)
        if schema is None:
            raise ConvertError(
                f"{name}: 本机 ComfyUI 没有节点 {class_type}（可能缺少对应的自定义节点包）"
            )

        column = depth[node_id]
        row = column_counts.get(column, 0)
        column_counts[column] = row + 1

        widgets: list[Any] = []
        input_slots: list[dict[str, Any]] = []
        api_inputs = api_node.get("inputs", {})

        for input_name, spec, optional in ordered_inputs(schema):
            value = api_inputs.get(input_name)
            if is_widget(spec) and not (isinstance(value, list) and len(value) == 2):
                widgets.append(value if value is not None else default_value(spec))
                options = spec_options(spec)
                if options.get("control_after_generate"):
                    widgets.append("fixed")
                if options.get("image_upload"):
                    widgets.append("image")
                continue
            slot_type = spec[0] if isinstance(spec[0], str) else "COMBO"
            input_slots.append(
                {
                    "name": input_name,
                    "type": slot_type,
                    "link": None,
                    **({"shape": 7} if optional else {}),
                }
            )

        output_types = schema.get("output") or []
        output_names = schema.get("output_name") or output_types
        outputs = [
            {
                "name": output_names[i] if i < len(output_names) else str(output_types[i]),
                "type": output_types[i] if isinstance(output_types[i], str) else "COMBO",
                "links": [],
                "slot_index": i,
            }
            for i in range(len(output_types))
        ]

        node: dict[str, Any] = {
            "id": int(node_id),
            "type": class_type,
            "pos": [80 + column * COLUMN_WIDTH, 80 + row * ROW_HEIGHT],
            "size": NODE_SIZES.get(class_type, DEFAULT_SIZE),
            "flags": {},
            "order": position,
            "mode": 0,
            "inputs": input_slots,
            "outputs": outputs,
            "properties": {"Node name for S&R": class_type},
            "widgets_values": widgets,
        }
        title = (api_node.get("_meta") or {}).get("title")
        if title:
            node["title"] = title
        nodes[node_id] = node

    # 建连线：必须等所有节点的槽位都建好
    for node_id in order:
        target = nodes[node_id]
        api_inputs = workflow[node_id].get("inputs", {})
        for slot_index, slot in enumerate(target["inputs"]):
            value = api_inputs.get(slot["name"])
            if not (isinstance(value, list) and len(value) == 2):
                continue
            origin_id, origin_slot = str(value[0]), int(value[1])
            if origin_id not in nodes:
                raise ConvertError(f"{name}: {node_id}.{slot['name']} 指向不存在的节点 {origin_id}")
            origin = nodes[origin_id]
            if origin_slot >= len(origin["outputs"]):
                raise ConvertError(
                    f"{name}: {node_id}.{slot['name']} 引用了 {origin['type']} 不存在的输出槽 {origin_slot}"
                )
            link_id += 1
            slot["link"] = link_id
            origin["outputs"][origin_slot]["links"].append(link_id)
            links.append(
                [
                    link_id,
                    int(origin_id),
                    origin_slot,
                    int(node_id),
                    slot_index,
                    origin["outputs"][origin_slot]["type"],
                ]
            )

    for node in nodes.values():
        for output in node["outputs"]:
            if not output["links"]:
                output["links"] = None

    return {
        "id": str(uuid.uuid4()),
        "revision": 0,
        "last_node_id": max(int(n) for n in workflow),
        "last_link_id": link_id,
        "nodes": [nodes[n] for n in order],
        "links": links,
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.7, "offset": [0, 0]}},
        "version": 0.4,
    }


def validate(ui: dict[str, Any], name: str) -> list[str]:
    problems: list[str] = []
    by_id = {node["id"]: node for node in ui["nodes"]}
    seen_links = {link[0] for link in ui["links"]}

    for link in ui["links"]:
        link_id, origin, origin_slot, target, target_slot, _ = link
        if origin not in by_id:
            problems.append(f"连线 {link_id} 的源节点 {origin} 不存在")
        if target not in by_id:
            problems.append(f"连线 {link_id} 的目标节点 {target} 不存在")

    for node in ui["nodes"]:
        for slot in node["inputs"]:
            if slot["link"] is not None and slot["link"] not in seen_links:
                problems.append(f"节点 {node['id']} 的输入 {slot['name']} 引用了不存在的连线")
        for output in node["outputs"]:
            for ref in output["links"] or []:
                if ref not in seen_links:
                    problems.append(f"节点 {node['id']} 的输出 {output['name']} 引用了不存在的连线")

    if problems:
        return [f"{name}: {p}" for p in problems]
    return []


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="API 工作流转 UI 工作流",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input", type=Path, default=None, help="单个 API 工作流；默认转换整个目录")
    p.add_argument("--api-dir", type=Path, default=REPO_ROOT / "workflows/api")
    p.add_argument("--out", type=Path, default=REPO_ROOT / "workflows/ui")
    p.add_argument("--server", default="127.0.0.1:8188")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sources = [args.input] if args.input else sorted(args.api_dir.glob("*.json"))
    if not sources:
        raise SystemExit(f"没有找到 API 工作流: {args.api_dir}")

    try:
        object_info = fetch_object_info(args.server)
    except ConvertError as exc:
        raise SystemExit(str(exc)) from exc

    args.out.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    for source in sources:
        workflow = json.loads(source.read_text(encoding="utf-8"))
        try:
            ui = convert(workflow, object_info, source.name)
        except ConvertError as exc:
            print(f"[失败] {source.name}: {exc}")
            problems.append(str(exc))
            continue
        problems.extend(validate(ui, source.name))
        dest = args.out / source.name
        dest.write_text(json.dumps(ui, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[生成] {dest}  节点 {len(ui['nodes'])}  连线 {len(ui['links'])}")

    if problems:
        print(f"\n发现 {len(problems)} 个问题：")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("\n全部转换完成，在 ComfyUI 里用 工作流 -> 打开 载入即可")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
