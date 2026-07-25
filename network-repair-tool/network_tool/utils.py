"""跨平台工具函数。"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
from typing import Iterable, Sequence, Tuple


IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"


def run_command(
    command: Sequence[str],
    *,
    timeout: int = 30,
    shell: bool = False,
    check: bool = False,
) -> Tuple[int, str, str]:
    """执行命令并返回 (returncode, stdout, stderr)。"""
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, command, result.stdout, result.stderr
            )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"命令超时 ({timeout}s): {' '.join(command)}"
    except FileNotFoundError:
        return -1, "", f"未找到命令: {command[0]}"
    except Exception as exc:  # noqa: BLE001 - CLI 工具需要兜底展示错误
        return -1, "", str(exc)


def ping_host(host: str, count: int = 2, timeout_sec: int = 3) -> Tuple[bool, str]:
    """Ping 指定主机，返回 (是否成功, 详情)。"""
    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_sec * 1000), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout_sec), host]

    code, stdout, stderr = run_command(cmd, timeout=timeout_sec * count + 5)
    success = code == 0
    detail = stdout or stderr or f"exit code {code}"
    return success, detail


def resolve_dns(hostname: str, timeout_sec: int = 5) -> Tuple[bool, str]:
    """测试 DNS 解析。"""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_sec)
    try:
        results = socket.getaddrinfo(hostname, None)
        addresses = sorted({item[4][0] for item in results})
        return True, ", ".join(addresses)
    except socket.gaierror as exc:
        return False, str(exc)
    finally:
        socket.setdefaulttimeout(old_timeout)


def check_tcp_port(host: str, port: int, timeout_sec: int = 5) -> Tuple[bool, str]:
    """测试 TCP 端口连通性。"""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True, f"{host}:{port} 可连接"
    except OSError as exc:
        return False, str(exc)


def require_admin() -> bool:
    """检查是否具有管理员/root 权限。"""
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0  # type: ignore[name-defined]


def format_status(ok: bool) -> str:
    return "正常" if ok else "异常"


def join_lines(lines: Iterable[str]) -> str:
    return "\n".join(lines)
