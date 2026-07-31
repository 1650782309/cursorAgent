"""ComfyUI HTTP API 的最小客户端，只依赖标准库。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, server: str = "127.0.0.1:8188", timeout: float = 30.0) -> None:
        if not server.startswith(("http://", "https://")):
            server = f"http://{server}"
        self.base = server.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise ComfyError(f"{path} 返回 HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ComfyError(f"无法连接 {url}: {exc.reason}") from exc
        return json.loads(body) if body else None

    def ping(self) -> None:
        """确认服务在线，顺便让连接错误尽早暴露。"""
        self._request("/system_stats")

    def submit(self, workflow: dict[str, Any], client_id: str) -> str:
        result = self._request("/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = (result or {}).get("prompt_id")
        if not prompt_id:
            raise ComfyError(f"提交后未拿到 prompt_id: {result}")
        return prompt_id

    def history(self, prompt_id: str) -> dict[str, Any] | None:
        result = self._request(f"/history/{prompt_id}")
        return (result or {}).get(prompt_id)

    def wait(self, prompt_id: str, poll: float = 1.0, timeout: float = 900.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            entry = self.history(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("completed") or entry.get("outputs"):
                    return entry
                if status.get("status_str") == "error":
                    raise ComfyError(f"任务 {prompt_id} 执行失败: {status}")
            time.sleep(poll)
        raise ComfyError(f"任务 {prompt_id} 等待超时（{timeout:.0f}s）")

    @staticmethod
    def collect_images(entry: dict[str, Any]) -> list[dict[str, str]]:
        images: list[dict[str, str]] = []
        for node_output in (entry.get("outputs") or {}).values():
            for image in node_output.get("images", []) or []:
                images.append(
                    {
                        "filename": image.get("filename", ""),
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    }
                )
        return images

    def download(self, image: dict[str, str], dest_dir: Path) -> Path:
        query = urllib.parse.urlencode(
            {
                "filename": image["filename"],
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "output"),
            }
        )
        url = f"{self.base}/view?{query}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(image["filename"]).name
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                dest.write_bytes(resp.read())
        except urllib.error.URLError as exc:
            raise ComfyError(f"下载失败 {url}: {exc}") from exc
        return dest
