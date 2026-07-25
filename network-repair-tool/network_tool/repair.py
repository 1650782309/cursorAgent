"""网络修复模块。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .detector import NetworkDetector, print_report
from .utils import IS_LINUX, IS_WINDOWS, require_admin, run_command


@dataclass
class RepairStep:
    name: str
    description: str
    action: Callable[[], tuple[bool, str]]
    requires_admin: bool = True
    destructive: bool = False


@dataclass
class RepairResult:
    step_name: str
    success: bool
    message: str


@dataclass
class RepairReport:
    steps_run: List[RepairResult] = field(default_factory=list)
    all_success: bool = False

    def add(self, result: RepairResult) -> None:
        self.steps_run.append(result)


class NetworkRepairer:
    """网络修复器，按从轻到重顺序执行修复步骤。"""

    LIGHT_STEPS = ["flush_dns", "renew_dhcp", "restart_services"]
    MEDIUM_STEPS = ["reset_adapter", "reset_routes"]
    HEAVY_STEPS = ["reset_winsock", "reset_tcpip"]

    def __init__(self) -> None:
        self.detector = NetworkDetector()

    def get_available_steps(self) -> List[RepairStep]:
        steps: List[RepairStep] = [
            RepairStep("flush_dns", "刷新 DNS 缓存", self._flush_dns, requires_admin=False),
            RepairStep("renew_dhcp", "释放并重新获取 IP 地址", self._renew_dhcp),
            RepairStep("restart_services", "重启网络相关服务", self._restart_services),
            RepairStep("reset_adapter", "重置网络适配器（禁用再启用）", self._reset_adapter),
            RepairStep("reset_routes", "刷新路由表", self._reset_routes),
        ]

        if IS_WINDOWS:
            steps.extend(
                [
                    RepairStep(
                        "reset_winsock",
                        "重置 Winsock 目录（修复游戏/Vanguard 导致的栈损坏）",
                        self._reset_winsock,
                        destructive=True,
                    ),
                    RepairStep(
                        "reset_tcpip",
                        "重置 TCP/IP 协议栈",
                        self._reset_tcpip,
                        destructive=True,
                    ),
                ]
            )

        if IS_LINUX:
            steps.append(
                RepairStep(
                    "restart_network_manager",
                    "重启 NetworkManager",
                    self._restart_network_manager,
                )
            )

        return steps

    def run_repair(
        self,
        level: str = "auto",
        step_names: Optional[List[str]] = None,
        verify: bool = True,
    ) -> RepairReport:
        """执行修复。

        level: light | medium | heavy | full | auto
        """
        report = RepairReport()
        available = {s.name: s for s in self.get_available_steps()}

        if step_names:
            selected = [available[n] for n in step_names if n in available]
        elif level == "light":
            selected = [available[n] for n in self.LIGHT_STEPS if n in available]
        elif level == "medium":
            names = self.LIGHT_STEPS + self.MEDIUM_STEPS
            selected = [available[n] for n in names if n in available]
        elif level == "heavy" or level == "full":
            names = self.LIGHT_STEPS + self.MEDIUM_STEPS + self.HEAVY_STEPS
            selected = [available[n] for n in names if n in available]
        else:
            # auto: 根据检测结果选择
            selected = self._select_steps_by_diagnosis(available)

        if not selected:
            report.add(RepairResult("无操作", False, "没有可执行的修复步骤"))
            return report

        is_admin = require_admin()
        for step in selected:
            if step.requires_admin and not is_admin:
                report.add(
                    RepairResult(
                        step.name,
                        False,
                        "需要管理员权限，请以管理员身份运行",
                    )
                )
                continue

            print(f"\n>>> 正在执行: {step.description}...")
            ok, msg = step.action()
            report.add(RepairResult(step.name, ok, msg))
            print(f"    {'✓' if ok else '✗'} {msg}")
            time.sleep(1)

        report.all_success = all(r.success for r in report.steps_run)

        if verify:
            print("\n>>> 修复完成，正在重新检测网络...")
            time.sleep(2)
            diag = self.detector.run_all_checks()
            print_report(diag, verbose=False)

        return report

    def _select_steps_by_diagnosis(self, available: dict) -> List[RepairStep]:
        diag = self.detector.run_all_checks()
        selected_names: List[str] = list(self.LIGHT_STEPS)

        failed_names = {c.name for c in diag.checks if not c.ok}

        if any("Ping" in n for n in failed_names) or "默认路由" in failed_names:
            selected_names.extend(self.MEDIUM_STEPS)

        if any("DNS" in n for n in failed_names):
            if "flush_dns" not in selected_names:
                selected_names.insert(0, "flush_dns")

        if "Winsock 目录" in failed_names or "Windows 网络服务" in failed_names:
            selected_names.extend(self.HEAVY_STEPS)

        if "无畏契约进程" in failed_names or any(
            c.name == "无畏契约进程" and c.details for c in diag.checks
        ):
            # 游戏在运行时，优先轻量修复；若仍失败用户可手动 heavy
            pass

        # 去重保序
        seen = set()
        ordered = []
        for name in selected_names:
            if name not in seen and name in available:
                seen.add(name)
                ordered.append(available[name])
        return ordered

    def _flush_dns(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            code, stdout, stderr = run_command(["ipconfig", "/flushdns"], timeout=15)
            return code == 0, stdout or stderr or "DNS 缓存已刷新"

        for cmd in (
            ["resolvectl", "flush-caches"],
            ["systemd-resolve", "--flush-caches"],
            ["service", "nscd", "restart"],
        ):
            code, stdout, stderr = run_command(cmd, timeout=15)
            if code == 0:
                return True, f"DNS 缓存已刷新 ({cmd[0]})"
        return False, "无法刷新 DNS 缓存，请手动检查"

    def _renew_dhcp(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            run_command(["ipconfig", "/release"], timeout=30)
            code, stdout, stderr = run_command(["ipconfig", "/renew"], timeout=60)
            return code == 0, stdout.splitlines()[-1] if stdout else stderr or "IP 已更新"

        code, stdout, stderr = run_command(["dhclient", "-r"], timeout=20)
        code2, stdout2, stderr2 = run_command(["dhclient"], timeout=30)
        ok = code2 == 0 or code == 0
        return ok, (stdout2 or stderr2 or "DHCP 已更新")[:200]

    def _restart_services(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            services = ["Dnscache", "Dhcp", "NlaSvc"]
            results = []
            for svc in services:
                run_command(["net", "stop", svc], timeout=30)
                code, _, stderr = run_command(["net", "start", svc], timeout=30)
                results.append(f"{svc}: {'OK' if code == 0 else stderr[:50]}")
            return True, "; ".join(results)

        return self._restart_network_manager()

    def _reset_adapter(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            ps_script = """
$adapter = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.Virtual -eq $false } | Select-Object -First 1
if (-not $adapter) {
    $adapter = Get-NetAdapter | Where-Object { $_.Virtual -eq $false } | Select-Object -First 1
}
if ($adapter) {
    Disable-NetAdapter -Name $adapter.Name -Confirm:$false
    Start-Sleep -Seconds 3
    Enable-NetAdapter -Name $adapter.Name -Confirm:$false
    Write-Output "已重置适配器: $($adapter.Name)"
} else {
    Write-Error "未找到可用网卡"
    exit 1
}
"""
            code, stdout, stderr = run_command(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                timeout=60,
            )
            return code == 0, stdout or stderr

        code, stdout, stderr = run_command(["nmcli", "networking", "off"], timeout=15)
        time.sleep(2)
        code2, stdout2, stderr2 = run_command(["nmcli", "networking", "on"], timeout=15)
        ok = code2 == 0
        return ok, "NetworkManager 网络已重置" if ok else stderr2

    def _reset_routes(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            code, stdout, stderr = run_command(["route", "/f"], timeout=10)
            if code != 0:
                return False, stderr or "路由刷新失败"
            code2, _, stderr2 = run_command(["ipconfig", "/renew"], timeout=60)
            return code2 == 0, "路由表已刷新并重新获取 IP"

        code, stdout, stderr = run_command(["ip", "route", "flush", "cache"], timeout=10)
        return code == 0, stdout or stderr or "路由缓存已刷新"

    def _reset_winsock(self) -> tuple[bool, str]:
        code, stdout, stderr = run_command(["netsh", "winsock", "reset"], timeout=30)
        msg = stdout or stderr
        if code == 0:
            msg += "（建议重启电脑使更改完全生效）"
        return code == 0, msg

    def _reset_tcpip(self) -> tuple[bool, str]:
        code, stdout, stderr = run_command(["netsh", "int", "ip", "reset"], timeout=30)
        msg = stdout or stderr
        if code == 0:
            msg += "（建议重启电脑使更改完全生效）"
        return code == 0, msg

    def _restart_network_manager(self) -> tuple[bool, str]:
        code, stdout, stderr = run_command(
            ["systemctl", "restart", "NetworkManager"],
            timeout=30,
        )
        return code == 0, stdout or stderr or "NetworkManager 已重启"


def print_repair_report(report: RepairReport) -> None:
    print("\n" + "=" * 60)
    print("  修复结果")
    print("=" * 60)
    for item in report.steps_run:
        icon = "✓" if item.success else "✗"
        print(f"[{icon}] {item.step_name}: {item.message}")
    print(f"\n总体: {'全部成功' if report.all_success else '部分步骤失败'}")
    print("=" * 60)
