#!/usr/bin/env python3
"""仓库自测：不需要 GPU、不需要 ComfyUI，也不需要第三方库。

改过词库、模板或工作流之后跑一遍，确认整条链路没坏：

  python scripts/selftest.py

检查项：
  1. 每个词库都能读、非空、无重复条目
  2. 每个模板引用的词库都存在，且能在限定层数内展开
  3. 每个工作流 JSON 的节点引用合法、必需标记齐全
  4. PNG 元数据解析正确（自己造一张带参数的 PNG 再读回来）
  5. 用桩服务器跑完整的提交—轮询—下载流程
"""

from __future__ import annotations

import json
import random
import struct
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_generate import main as batch_main  # noqa: E402
from comfy_client import ComfyClient  # noqa: E402
from index_outputs import read_png_text  # noqa: E402
from wildcard import WildcardResolver, load_template  # noqa: E402

REQUIRED_TITLES = ("POSITIVE", "SAMPLER")
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(f"{name}: {detail}")


def test_wildcards() -> None:
    print("[1/5] 词库")
    resolver = WildcardResolver(REPO_ROOT / "wildcards")
    names = resolver.names()
    check("词库文件存在", bool(names), f"{len(names)} 个")
    for name in names:
        entries = resolver.entries(name)
        duplicates = {e for e in entries if entries.count(e) > 1}
        check(
            f"{name} ({len(entries)} 条)",
            not duplicates,
            f"重复条目: {sorted(duplicates)}" if duplicates else "",
        )


def test_templates() -> None:
    print("[2/5] 模板展开")
    rng = random.Random(0)
    resolver = WildcardResolver(REPO_ROOT / "wildcards", rng)
    templates = sorted((REPO_ROOT / "prompts/templates").glob("*.txt"))
    check("模板文件存在", bool(templates), f"{len(templates)} 个")
    for path in templates:
        template = load_template(path)
        try:
            # 多次展开，尽量覆盖到不同的随机分支
            for _ in range(30):
                prompt, picks = resolver.resolve(template)
                assert prompt, "展开结果为空"
                assert "__" not in prompt, f"仍有未展开的词库: {prompt}"
                assert "{" not in prompt, f"仍有未展开的选择项: {prompt}"
            check(f"{path.name}（{len(picks)} 个维度）", True)
        except Exception as exc:  # noqa: BLE001 - 自测脚本汇总所有错误
            check(path.name, False, str(exc))


def test_workflows() -> None:
    print("[3/5] 工作流")
    paths = sorted((REPO_ROOT / "workflows/api").glob("*.json"))
    check("工作流文件存在", bool(paths), f"{len(paths)} 个")
    for path in paths:
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
            titles = {
                (node.get("_meta") or {}).get("title") for node in workflow.values()
            }
            for node_id, node in workflow.items():
                assert "class_type" in node, f"节点 {node_id} 缺少 class_type"
                for key, value in node.get("inputs", {}).items():
                    if isinstance(value, list):
                        assert len(value) == 2, f"{node_id}.{key} 链接格式错误"
                        assert value[0] in workflow, f"{node_id}.{key} 指向不存在的节点 {value[0]}"
            missing = [t for t in REQUIRED_TITLES if t not in titles]
            assert not missing, f"缺少必需标记 {missing}"
            check(f"{path.name}（{len(workflow)} 节点）", True)
        except Exception as exc:  # noqa: BLE001
            check(path.name, False, str(exc))


def make_png(path: Path, payload: dict) -> None:
    """造一张 1x1 PNG，把工作流写进 tEXt 块，模拟 ComfyUI 的产出。"""

    def chunk(ctype: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + ctype
            + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff")
    text = b"prompt\x00" + json.dumps(payload).encode("utf-8")
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"tEXt", text)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def test_png_metadata(tmp_dir: Path) -> None:
    print("[4/5] PNG 元数据")
    workflow = json.loads(
        (REPO_ROOT / "workflows/api/01_divergence_sdxl.json").read_text(encoding="utf-8")
    )
    workflow["3"]["inputs"]["text"] = "1girl, solo, 自测中文提示词"
    workflow["6"]["inputs"]["seed"] = 123456
    png = tmp_dir / "sample.png"
    make_png(png, workflow)

    meta = read_png_text(png)
    check("读到 prompt 文本块", "prompt" in meta)
    if "prompt" in meta:
        parsed = json.loads(meta["prompt"])
        check("提示词还原一致", parsed["3"]["inputs"]["text"] == "1girl, solo, 自测中文提示词")
        check("seed 还原一致", parsed["6"]["inputs"]["seed"] == 123456)

    from index_outputs import main as index_main

    code = index_main(["--root", str(tmp_dir)])
    check("索引脚本退出码", code == 0, f"code={code}")
    index = [json.loads(ln) for ln in (tmp_dir / "index.jsonl").read_text("utf-8").splitlines()]
    check("索引记录数", len(index) == 1, f"{len(index)} 条")
    if index:
        check("索引抽出 seed", index[0].get("seed") == 123456, str(index[0].get("seed")))
        check(
            "索引抽出底模",
            index[0].get("checkpoint") == "illustriousXL.safetensors",
            str(index[0].get("checkpoint")),
        )


class StubHandler(BaseHTTPRequestHandler):
    """最小 ComfyUI 桩服务：够 comfy_client 走完一轮就行。"""

    submitted: dict[str, dict] = {}
    image_bytes = b""

    def log_message(self, *_args) -> None:  # 静音
        pass

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        parsed = urlparse(self.path)
        if parsed.path == "/system_stats":
            self._json({"system": {"comfyui_version": "stub"}})
        elif parsed.path.startswith("/history/"):
            prompt_id = parsed.path.rsplit("/", 1)[-1]
            if prompt_id in self.submitted:
                self._json(
                    {
                        prompt_id: {
                            "status": {"completed": True},
                            "outputs": {
                                "8": {
                                    "images": [
                                        {
                                            "filename": f"{prompt_id}.png",
                                            "subfolder": "selftest",
                                            "type": "output",
                                        }
                                    ]
                                }
                            },
                        }
                    }
                )
            else:
                self._json({})
        elif parsed.path == "/view":
            query = parse_qs(parsed.query)
            assert "filename" in query
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(self.image_bytes)))
            self.end_headers()
            self.wfile.write(self.image_bytes)
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if urlparse(self.path).path != "/prompt":
            self.send_error(404)
            return
        workflow = payload.get("prompt", {})
        prompt_id = f"stub-{len(self.submitted):04d}"
        self.submitted[prompt_id] = workflow
        self._json({"prompt_id": prompt_id, "number": len(self.submitted)})


def test_end_to_end(tmp_dir: Path) -> None:
    print("[5/5] 端到端（桩服务器）")
    StubHandler.submitted = {}
    StubHandler.image_bytes = (tmp_dir / "sample.png").read_bytes()
    server = HTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"127.0.0.1:{server.server_port}"

    try:
        client = ComfyClient(address, timeout=5.0)
        client.ping()
        check("桩服务连通", True, address)

        run_root = tmp_dir / "runs"
        code = batch_main(
            [
                "--axis", "design/silhouette",
                "--limit", "3",
                "--fixed-seed", "20260731",
                "--label", "selftest",
                "--server", address,
                "--out", str(run_root),
                "--download",
                "--queue-ahead", "2",
            ]
        )
        check("批量脚本退出码", code == 0, f"code={code}")

        run_dirs = sorted(run_root.glob("*-selftest"))
        check("生成批次目录", len(run_dirs) == 1, str([p.name for p in run_dirs]))
        if not run_dirs:
            return
        run_dir = run_dirs[0]

        records = [
            json.loads(ln)
            for ln in (run_dir / "manifest.jsonl").read_text("utf-8").splitlines()
        ]
        check("manifest 记录数", len(records) == 3, f"{len(records)} 条")
        check("提交到桩服务的任务数", len(StubHandler.submitted) == 3)
        check("seed 全部固定", all(r["seed"] == 20260731 for r in records))
        check(
            "扫描轴取值互不相同",
            len({r["axis"]["design/silhouette"] for r in records}) == 3,
        )
        check(
            "输出子目录按轴取值分开",
            len({r["subfolder"] for r in records}) == 3,
            str([r["subfolder"] for r in records]),
        )
        check("图片已下载", all(r.get("local") for r in records))

        # 提交给服务端的工作流里，提示词与 seed 必须真的被替换过
        workflows = list(StubHandler.submitted.values())
        check(
            "工作流注入了提示词",
            all("masterpiece" in wf["3"]["inputs"]["text"] for wf in workflows),
        )
        check(
            "工作流注入了固定 seed",
            all(wf["6"]["inputs"]["seed"] == 20260731 for wf in workflows),
        )
        check(
            "工作流注入了输出前缀",
            all(wf["8"]["inputs"]["filename_prefix"].startswith("selftest/") for wf in workflows),
        )
        run_config = json.loads((run_dir / "run.json").read_text("utf-8"))
        check("run.json 记录了底模", run_config["models"].get("ckpt_name") is not None)
    finally:
        server.shutdown()
        server.server_close()


def main() -> int:
    import tempfile

    print("仓库自测开始\n")
    test_wildcards()
    test_templates()
    test_workflows()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        test_png_metadata(tmp_dir)
        test_end_to_end(tmp_dir)

    print()
    if failures:
        print(f"自测失败 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("自测全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
