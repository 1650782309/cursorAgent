"""网络状态检测模块。"""

from __future__ import annotations

import json
import platform
import re
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .utils import (
    IS_LINUX,
    IS_WINDOWS,
    check_tcp_port,
    format_status,
    ping_host,
    resolve_dns,
    run_command,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    details: str = ""


@dataclass
class NetworkReport:
    timestamp: str
    platform: str
    hostname: str
    checks: List[CheckResult] = field(default_factory=list)
    overall_ok: bool = False
    summary: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


VALORANT_PROCESS_NAMES = [
    "VALORANT-Win64-Shipping.exe",
    "VALORANT.exe",
    "RiotClientServices.exe",
    "RiotClientUx.exe",
    "vgc.exe",
    "vgtray.exe",
]

PING_TARGETS = ["223.5.5.5", "114.114.114.114", "8.8.8.8"]
DNS_TARGETS = ["www.baidu.com", "www.qq.com", "www.google.com"]
TCP_TARGETS = [("223.5.5.5", 443), ("114.114.114.114", 443)]


class NetworkDetector:
    """综合网络状态检测器。"""

    def run_all_checks(self) -> NetworkReport:
        checks: List[CheckResult] = []

        checks.append(self._check_interfaces())
        checks.append(self._check_default_route())
        checks.append(self._check_local_dns())
        checks.extend(self._check_ping_targets())
        checks.extend(self._check_dns_resolution())
        checks.extend(self._check_tcp_connectivity())

        if IS_WINDOWS:
            checks.append(self._check_windows_network_services())
            checks.append(self._check_valorant_processes())
            checks.append(self._check_winsock_catalog())

        if IS_LINUX:
            checks.append(self._check_network_manager())

        overall_ok = all(item.ok for item in checks)
        failed = [item.name for item in checks if not item.ok]

        if overall_ok:
            summary = "网络状态正常，所有检测项通过。"
        else:
            summary = f"检测到 {len(failed)} 项异常: {', '.join(failed)}"

        return NetworkReport(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            platform=platform.platform(),
            hostname=socket.gethostname(),
            checks=checks,
            overall_ok=overall_ok,
            summary=summary,
        )

    def _check_interfaces(self) -> CheckResult:
        if IS_WINDOWS:
            code, stdout, stderr = run_command(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-NetAdapter | Select-Object Name, Status, LinkSpeed, InterfaceDescription | ConvertTo-Json",
                ],
                timeout=15,
            )
            if code != 0:
                return CheckResult("网卡状态", False, "无法获取网卡信息", stderr or stdout)

            try:
                data = json.loads(stdout) if stdout.startswith("[") else [json.loads(stdout)]
            except json.JSONDecodeError:
                data = []

            up_adapters = [d for d in data if str(d.get("Status", "")).lower() == "up"]
            if up_adapters:
                names = ", ".join(str(d.get("Name", "?")) for d in up_adapters)
                return CheckResult("网卡状态", True, f"{len(up_adapters)} 块网卡在线", names)
            return CheckResult("网卡状态", False, "没有处于 Up 状态的网卡", stdout or stderr)

        code, stdout, stderr = run_command(["ip", "-br", "link"], timeout=10)
        if code != 0:
            # 无 ip 命令时回退到 /sys/class/net
            try:
                net_path = Path("/sys/class/net")
                up_ifaces = [
                    p.name
                    for p in net_path.iterdir()
                    if p.name != "lo"
                    and (p / "operstate").exists()
                    and (p / "operstate").read_text(encoding="utf-8").strip() == "up"
                ]
                if up_ifaces:
                    return CheckResult(
                        "网卡状态",
                        True,
                        f"{len(up_ifaces)} 块网卡在线",
                        ", ".join(up_ifaces),
                    )
            except OSError:
                pass
            return CheckResult("网卡状态", False, "无法获取网卡信息", stderr or stdout)

        up_lines = [line for line in stdout.splitlines() if " UP " in line.upper()]
        if up_lines:
            return CheckResult("网卡状态", True, f"{len(up_lines)} 块网卡在线", "\n".join(up_lines))
        return CheckResult("网卡状态", False, "没有处于 UP 状态的网卡", stdout)

    def _check_default_route(self) -> CheckResult:
        if IS_WINDOWS:
            code, stdout, stderr = run_command(["route", "print", "0.0.0.0"], timeout=10)
            if code != 0:
                return CheckResult("默认路由", False, "无法读取路由表", stderr or stdout)

            gateway_match = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", stdout)
            if gateway_match:
                gw = gateway_match.group(1)
                ok, detail = ping_host(gw, count=1, timeout_sec=2)
                return CheckResult(
                    "默认路由",
                    ok,
                    f"网关 {gw} {'可达' if ok else '不可达'}",
                    detail,
                )
            return CheckResult("默认路由", False, "未找到默认网关", stdout[:500])

        code, stdout, stderr = run_command(["ip", "route", "show", "default"], timeout=10)
        if code != 0 or not stdout.strip():
            return CheckResult("默认路由", False, "未找到默认路由", stderr or stdout)
        gw_match = re.search(r"default via (\S+)", stdout)
        if gw_match:
            gw = gw_match.group(1)
            ok, detail = ping_host(gw, count=1, timeout_sec=2)
            return CheckResult("默认路由", ok, f"网关 {gw}", detail)
        return CheckResult("默认路由", True, "存在默认路由", stdout)

    def _check_local_dns(self) -> CheckResult:
        if IS_WINDOWS:
            code, stdout, stderr = run_command(["ipconfig", "/all"], timeout=15)
            if code != 0:
                return CheckResult("DNS 配置", False, "无法读取 DNS 配置", stderr)
            dns_filtered = re.findall(r"^\s+(\d+\.\d+\.\d+\.\d+)\s*$", stdout, re.MULTILINE)
            if dns_filtered:
                unique = list(dict.fromkeys(dns_filtered))
                return CheckResult(
                    "DNS 配置",
                    True,
                    f"已配置 {len(unique)} 个 DNS",
                    ", ".join(unique[:5]),
                )
            return CheckResult("DNS 配置", False, "未检测到 DNS 服务器", stdout[:300])

        try:
            with open("/etc/resolv.conf", encoding="utf-8") as f:
                content = f.read()
            nameservers = re.findall(r"^nameserver\s+(\S+)", content, re.MULTILINE)
            if nameservers:
                return CheckResult(
                    "DNS 配置",
                    True,
                    f"已配置 {len(nameservers)} 个 DNS",
                    ", ".join(nameservers),
                )
            return CheckResult("DNS 配置", False, "resolv.conf 中无 nameserver", content[:200])
        except OSError as exc:
            return CheckResult("DNS 配置", False, "无法读取 DNS 配置", str(exc))

    def _check_ping_targets(self) -> List[CheckResult]:
        results = []
        for target in PING_TARGETS:
            ok, detail = ping_host(target, count=2, timeout_sec=3)
            results.append(
                CheckResult(
                    f"Ping {target}",
                    ok,
                    format_status(ok),
                    detail.splitlines()[0] if detail else "",
                )
            )
        return results

    def _check_dns_resolution(self) -> List[CheckResult]:
        results = []
        for host in DNS_TARGETS:
            ok, detail = resolve_dns(host)
            results.append(
                CheckResult(
                    f"DNS 解析 {host}",
                    ok,
                    detail if ok else "解析失败",
                    detail,
                )
            )
        return results

    def _check_tcp_connectivity(self) -> List[CheckResult]:
        results = []
        for host, port in TCP_TARGETS:
            ok, detail = check_tcp_port(host, port)
            results.append(CheckResult(f"TCP {host}:{port}", ok, format_status(ok), detail))
        return results

    def _check_windows_network_services(self) -> CheckResult:
        services = ["Dnscache", "Dhcp", "NlaSvc", "Netman"]
        stopped = []
        details = []
        for svc in services:
            code, stdout, _ = run_command(["sc", "query", svc], timeout=10)
            running = "RUNNING" in stdout
            details.append(f"{svc}: {'运行中' if running else '未运行'}")
            if not running:
                stopped.append(svc)

        ok = len(stopped) == 0
        return CheckResult(
            "Windows 网络服务",
            ok,
            "全部运行中" if ok else f"{len(stopped)} 个服务未运行",
            "; ".join(details),
        )

    def _check_valorant_processes(self) -> CheckResult:
        code, stdout, stderr = run_command(["tasklist", "/FO", "CSV", "/NH"], timeout=15)
        if code != 0:
            return CheckResult("无畏契约进程", False, "无法枚举进程", stderr)

        running = [name for name in VALORANT_PROCESS_NAMES if name.lower() in stdout.lower()]
        if running:
            return CheckResult(
                "无畏契约进程",
                True,
                f"检测到 {len(running)} 个相关进程（游戏/Vanguard 可能影响网络）",
                ", ".join(running),
            )
        return CheckResult("无畏契约进程", True, "未检测到相关进程", "")

    def _check_winsock_catalog(self) -> CheckResult:
        code, stdout, stderr = run_command(["netsh", "winsock", "show", "catalog"], timeout=20)
        if code != 0:
            return CheckResult("Winsock 目录", False, "无法读取 Winsock 目录", stderr or stdout)

        entry_count = len(re.findall(r"^\s*\d+\)", stdout, re.MULTILINE))
        if entry_count >= 10:
            return CheckResult("Winsock 目录", True, f"目录正常 ({entry_count} 项)", "")
        return CheckResult(
            "Winsock 目录",
            False,
            f"目录项偏少 ({entry_count})，可能已损坏",
            stdout[:400],
        )

    def _check_network_manager(self) -> CheckResult:
        code, stdout, stderr = run_command(["systemctl", "is-active", "NetworkManager"], timeout=10)
        if "not been booted with systemd" in stderr or "Failed to connect to bus" in stderr:
            return CheckResult("NetworkManager", True, "非 systemd 环境，已跳过", "")
        active = stdout.strip() == "active"
        return CheckResult(
            "NetworkManager",
            active,
            "运行中" if active else "未运行",
            stderr or stdout,
        )


def print_report(report: NetworkReport, verbose: bool = False) -> None:
    """格式化打印检测报告。"""
    print("=" * 60)
    print("  网络状态检测报告")
    print("=" * 60)
    print(f"时间:     {report.timestamp}")
    print(f"主机:     {report.hostname}")
    print(f"系统:     {report.platform}")
    print(f"总体:     {'✓ 正常' if report.overall_ok else '✗ 异常'}")
    print(f"摘要:     {report.summary}")
    print("-" * 60)

    for check in report.checks:
        icon = "✓" if check.ok else "✗"
        print(f"[{icon}] {check.name}: {check.message}")
        if verbose and check.details:
            for line in check.details.splitlines()[:5]:
                print(f"    {line}")

    print("=" * 60)
