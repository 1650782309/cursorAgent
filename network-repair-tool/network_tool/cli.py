"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .detector import NetworkDetector, VALORANT_PROCESS_NAMES, print_report
from .repair import NetworkRepairer, print_repair_report
from .utils import IS_WINDOWS, require_admin, run_command


def cmd_detect(args: argparse.Namespace) -> int:
    detector = NetworkDetector()
    report = detector.run_all_checks()

    if args.json:
        print(report.to_json())
    else:
        print_report(report, verbose=args.verbose)

    return 0 if report.overall_ok else 1


def cmd_repair(args: argparse.Namespace) -> int:
    if args.level in ("heavy", "full") and not args.yes:
        print("警告: 重度修复会重置 Winsock/TCP/IP，可能需要重启电脑。")
        answer = input("确认继续? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消。")
            return 0

    if not require_admin() and args.level != "light":
        print("提示: 当前未以管理员身份运行，部分修复步骤可能失败。")
        print("Windows 请右键「以管理员身份运行」PowerShell/CMD 后执行本工具。")

    repairer = NetworkRepairer()
    step_names = args.steps.split(",") if args.steps else None
    report = repairer.run_repair(
        level=args.level,
        step_names=step_names,
        verify=not args.no_verify,
    )
    print_repair_report(report)
    return 0 if report.all_success else 1


def cmd_monitor(args: argparse.Namespace) -> int:
    detector = NetworkDetector()
    repairer = NetworkRepairer()
    interval = args.interval
    auto_fix = args.auto_fix

    print(f"开始监控网络状态，间隔 {interval} 秒。按 Ctrl+C 停止。")
    if auto_fix:
        print("已启用自动修复（检测到异常时执行轻量修复）。")

    try:
        while True:
            report = detector.run_all_checks()
            status = "正常" if report.overall_ok else "异常"
            print(f"\n[{report.timestamp}] 网络: {status} — {report.summary}")

            if not report.overall_ok:
                failed = [c for c in report.checks if not c.ok]
                for c in failed[:5]:
                    print(f"  ✗ {c.name}: {c.message}")

                if auto_fix:
                    print("  >>> 触发自动修复...")
                    repairer.run_repair(level="light", verify=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n监控已停止。")
        return 0


def _valorant_running() -> bool:
    if not IS_WINDOWS:
        return False
    code, stdout, _ = run_command(["tasklist", "/FO", "CSV", "/NH"], timeout=15)
    if code != 0:
        return False
    return any(name.lower() in stdout.lower() for name in VALORANT_PROCESS_NAMES)


def cmd_watch(args: argparse.Namespace) -> int:
    """监控无畏契约进程，网络异常时自动修复。"""
    if not IS_WINDOWS:
        print("watch 模式主要面向 Windows + 无畏契约 场景。")
        print("当前系统仍可使用 monitor 模式进行通用监控。")

    detector = NetworkDetector()
    repairer = NetworkRepairer()
    interval = args.interval

    print("=" * 60)
    print("  无畏契约网络监控模式")
    print("=" * 60)
    print("说明:")
    print("  - 持续检测网络连通性")
    print("  - 若检测到无畏契约/Vanguard 相关进程，会记录状态")
    print("  - 网络异常时自动尝试修复（无需重启电脑）")
    print("  - 若轻/中度修复无效，请手动运行: net-repair repair --level heavy")
    print("按 Ctrl+C 停止。\n")

    last_game_state = False
    failure_count = 0

    try:
        while True:
            game_running = _valorant_running()
            if game_running != last_game_state:
                if game_running:
                    print("[!] 检测到无畏契约相关进程已启动，开始密切监控网络...")
                else:
                    print("[i] 无畏契约相关进程已退出。")
                last_game_state = game_running

            report = detector.run_all_checks()

            if report.overall_ok:
                failure_count = 0
                print(f"[{report.timestamp}] ✓ 网络正常")
            else:
                failure_count += 1
                print(f"[{report.timestamp}] ✗ 网络异常 (连续 {failure_count} 次)")
                print(f"    {report.summary}")

                if failure_count >= args.threshold:
                    level = "medium" if failure_count >= args.threshold + 2 else "light"
                    print(f"    >>> 自动修复 (级别: {level})...")
                    repairer.run_repair(level=level, verify=True)
                    failure_count = 0

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n监控已停止。")
        return 0


def cmd_list_steps(_: argparse.Namespace) -> int:
    repairer = NetworkRepairer()
    print("可用修复步骤:\n")
    for step in repairer.get_available_steps():
        admin = "需要管理员" if step.requires_admin else "无需管理员"
        destructive = " [重度]" if step.destructive else ""
        print(f"  {step.name:25} {step.description} ({admin}){destructive}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="net-repair",
        description="网络状态检测与修复工具 — 适用于无畏契约等游戏导致断网场景",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="检测当前网络状态")
    p_detect.add_argument("-v", "--verbose", action="store_true", help="显示详细信息")
    p_detect.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_detect.set_defaults(func=cmd_detect)

    p_repair = sub.add_parser("repair", help="修复网络问题")
    p_repair.add_argument(
        "--level",
        choices=["auto", "light", "medium", "heavy", "full"],
        default="auto",
        help="修复强度: light=DNS/服务, medium=+网卡, heavy=+Winsock/TCP",
    )
    p_repair.add_argument(
        "--steps",
        help="指定步骤，逗号分隔 (如 flush_dns,renew_dhcp)",
    )
    p_repair.add_argument("--no-verify", action="store_true", help="修复后不重新检测")
    p_repair.add_argument("-y", "--yes", action="store_true", help="跳过重度修复确认")
    p_repair.set_defaults(func=cmd_repair)

    p_monitor = sub.add_parser("monitor", help="持续监控网络状态")
    p_monitor.add_argument("-i", "--interval", type=int, default=30, help="检测间隔(秒)")
    p_monitor.add_argument("--auto-fix", action="store_true", help="异常时自动轻量修复")
    p_monitor.set_defaults(func=cmd_monitor)

    p_watch = sub.add_parser("watch", help="监控无畏契约进程并在断网时自动修复")
    p_watch.add_argument("-i", "--interval", type=int, default=15, help="检测间隔(秒)")
    p_watch.add_argument(
        "-t",
        "--threshold",
        type=int,
        default=2,
        help="连续异常次数达到阈值后触发修复",
    )
    p_watch.set_defaults(func=cmd_watch)

    p_list = sub.add_parser("list-steps", help="列出所有修复步骤")
    p_list.set_defaults(func=cmd_list_steps)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
