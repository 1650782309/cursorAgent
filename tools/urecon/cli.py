"""urecon —— Unity 逆向学习流水线的编排器。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import exporters as exp_mod
from . import extract as extract_mod
from . import fingerprint as fp_mod
from . import inventory as inv_mod
from . import plan as plan_mod
from . import report as report_mod
from . import workspace as ws_mod
from .report import human
from .signatures import CATEGORY_LABEL
from .source import open_source

FP_CACHE = "fingerprint.json"
INV_CACHE = "inventory.json"


def _echo(msg: str = "") -> None:
    print(msg, file=sys.stdout)


def _load_fp(ws: ws_mod.Workspace, deep: bool, refresh: bool) -> fp_mod.Fingerprint:
    cache = ws.root / "notes" / FP_CACHE if (ws.root / "notes").exists() else None
    if cache and cache.exists() and not refresh:
        data = json.loads(cache.read_text(encoding="utf-8"))
        return _fp_from_dict(data)
    src = open_source(ws.source)
    return fp_mod.analyze(src, deep=deep)


def _fp_from_dict(d: dict) -> fp_mod.Fingerprint:
    fp = fp_mod.Fingerprint(target=d.get("target", "?"), source_kind=d.get("source_kind", "dir"))
    for k, v in d.items():
        if k in {"frameworks", "bundles"}:
            continue
        if hasattr(fp, k):
            setattr(fp, k, v)
    fp.frameworks = [fp_mod.Detected(**f) for f in d.get("frameworks", [])]
    fp.bundles = [fp_mod.BundleProbe(**b) for b in d.get("bundles", [])]
    return fp


def _print_fingerprint(fp: fp_mod.Fingerprint) -> None:
    _echo(f"目标        {fp.target}")
    _echo(f"平台        {fp.platform}" + (f"  [{', '.join(fp.architectures)}]" if fp.architectures else ""))
    _echo(f"Unity 版本  {fp.unity_version or '未识别'}"
          + (f"  (来自 {fp.unity_version_evidence})" if fp.unity_version_evidence else ""))
    _echo(f"脚本后端    {fp.backend}")
    if fp.metadata_path:
        enc = {True: "已加密", False: "明文", None: "未知"}[fp.metadata_encrypted]
        ver = f", 版本 {fp.metadata_version}" if fp.metadata_version else ""
        _echo(f"metadata    {fp.metadata_path}  ({enc}{ver})")
    _echo(f"规模        {fp.total_files} 个文件 / {human(fp.total_bytes)}")
    _echo(f"bundle 加密 {fp.bundle_encryption}")

    if fp.frameworks:
        _echo("")
        _echo("技术栈:")
        by_cat: dict[str, list] = {}
        for f in fp.frameworks:
            by_cat.setdefault(f.category, []).append(f.name)
        for cat, names in by_cat.items():
            _echo(f"  {CATEGORY_LABEL.get(cat, cat):<16} {'、'.join(names)}")

    if fp.warnings:
        _echo("")
        _echo("注意:")
        for w in fp.warnings:
            _echo(f"  ! {w}")


def cmd_init(args) -> int:
    ws = ws_mod.init(Path(args.workspace), Path(args.source))
    _echo(f"工作区已建立: {ws.root}")
    for d in ws_mod.SUBDIRS:
        _echo(f"  {d}/")
    _echo(f"源: {ws.source}")
    _echo("")
    _echo(f"下一步: urecon fingerprint {ws.root}")
    return 0


def cmd_fingerprint(args) -> int:
    ws = ws_mod.resolve(args.target)
    src = open_source(ws.source)
    fp = fp_mod.analyze(src, deep=not args.fast)
    if args.json:
        _echo(json.dumps(fp.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_fingerprint(fp)
    if ws.state_path.exists() or args.save:
        out = ws.dir("notes") / FP_CACHE
        out.write_text(json.dumps(fp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        ws.save_state({"fingerprint": fp.to_dict()})
        if not args.json:
            _echo("")
            _echo(f"已写入 {out}")
    return 0


def cmd_inventory(args) -> int:
    ws = ws_mod.resolve(args.target)
    src = open_source(ws.source)
    if not inv_mod.HAS_UNITYPY:
        _echo("! 未安装 UnityPy，降级为文件级统计。装上可得到对象级明细: pip install UnityPy")
    version = args.unity_version or _load_fp(ws, deep=False, refresh=False).unity_version
    inv = inv_mod.scan(
        src,
        max_containers=args.max_containers,
        max_objects=args.max_objects,
        unity_version=version,
    )
    outdir = Path(args.output) if args.output else ws.dir("notes")
    files = inv_mod.write_csv(inv, outdir)
    (outdir / INV_CACHE).write_text(
        json.dumps(inv.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _echo(f"解析引擎 {inv.engine}")
    _echo(f"容器 {len(inv.containers)} 个（失败 {inv.unparsed}），对象 {len(inv.objects)} 个")
    if inv.type_bytes:
        _echo("")
        _echo("体积分布:")
        total = sum(inv.type_bytes.values()) or 1
        for t, b in list(inv.type_bytes.items())[:12]:
            _echo(f"  {t:<20} {inv.type_count.get(t, 0):>7}  {human(b):>10}  {b / total * 100:5.1f}%")
    if inv.texture_formats:
        _echo("")
        _echo("贴图格式: " + "、".join(f"{k}×{v}" for k, v in list(inv.texture_formats.items())[:8]))
    if inv.audio_formats:
        _echo("音频格式: " + "、".join(f"{k}×{v}" for k, v in list(inv.audio_formats.items())[:8]))
    _echo("")
    for f in files + [outdir / INV_CACHE]:
        _echo(f"已写入 {f}")
    return 0


def cmd_plan(args) -> int:
    ws = ws_mod.resolve(args.target)
    fp = _load_fp(ws, deep=not args.fast, refresh=args.refresh)
    steps = plan_mod.build(fp, target=str(ws.source))
    _echo(f"针对 {fp.backend} / {fp.platform} / Unity {fp.unity_version or '?'} 的工具流:")
    _echo("")
    for i, s in enumerate(steps, 1):
        _echo(f"{i}. {s.title}")
        _echo(f"   为什么: {s.why}")
        for c in s.commands:
            _echo(f"   $ {c}")
        if s.fallback:
            _echo(f"   失败时: {s.fallback}")
        _echo("")
    return 0


def cmd_report(args) -> int:
    ws = ws_mod.resolve(args.target)
    fp = _load_fp(ws, deep=not args.fast, refresh=args.refresh)
    inv = None
    cache = ws.root / "notes" / INV_CACHE
    if args.with_inventory:
        src = open_source(ws.source)
        inv = inv_mod.scan(src, unity_version=fp.unity_version)
    elif cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        inv = inv_mod.Inventory(
            engine=data.get("engine", "?"),
            type_count=data.get("type_count", {}),
            type_bytes=data.get("type_bytes", {}),
            texture_formats=data.get("texture_formats", {}),
            audio_formats=data.get("audio_formats", {}),
            unparsed=data.get("unparsed_containers", 0),
        )
    steps = plan_mod.build(fp, target=str(ws.source))
    md = report_mod.render(fp, inv, steps, title=args.title)
    out = Path(args.output) if args.output else ws.dir("notes") / "report.md"
    if out.is_dir():
        out = out / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    _echo(f"报告已写入 {out}")
    _echo("第 5、6 节留空了，必须手写——见 docs/06-learning-loop.md")
    return 0


def cmd_compare(args) -> int:
    rows = []
    for p in args.states:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        rows.append(data.get("fingerprint", data))
    md = report_mod.render_compare(rows)
    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        _echo(f"已写入 {args.output}")
    else:
        _echo(md)
    return 0


def cmd_extract(args) -> int:
    ws = ws_mod.resolve(args.target)
    src = open_source(ws.source)
    version = args.unity_version
    if not version:
        try:
            version = _load_fp(ws, deep=False, refresh=False).unity_version
        except Exception:
            version = None

    outdir = Path(args.output) if args.output else ws.dir("extracted")
    fmt = "classify-only" if args.classify_only else args.format
    report = extract_mod.extract(
        src,
        outdir,
        unity_version=version,
        format=fmt,
        max_containers=args.max_containers,
        prefer=args.exporter,
        vendor_dir=Path(args.vendor) if args.vendor else None,
    )

    _echo(f"后端      {report.backend}"
          + (f"  ({report.exporter_path})" if report.exporter_path else ""))
    _echo(f"提取      {len(report.items)} 项")
    if report.counts:
        _echo("分类:")
        from .classify import CATEGORY_DIRS
        for key, label in CATEGORY_DIRS.items():
            n = report.counts.get(key, 0)
            if n:
                _echo(f"  {label:<6} {n}")
    for n in report.notes[:8]:
        _echo(f"! {n}")
    for e in report.errors[:5]:
        _echo(f"× {e}")
    _echo(f"清单      {outdir / 'models' / '_index.json'}")
    _echo(f"摘要      {outdir / 'models' / '_summary.md'}")

    if args.format == "fbx" and report.backend not in {"assetstudio"}:
        _echo("")
        _echo("可播放 FBX 需要 AssetStudio：")
        _echo("  1) bash scripts/fetch_tools.sh   # 或手动下载到 vendor/")
        _echo("  2) set URECON_ASSETSTUDIO=<AssetStudio.CLI 路径>")
        _echo("  3) urecon extract <target> --format fbx")
        return 0 if report.items else 1
    return 0


def cmd_doctor(args) -> int:
    exp = exp_mod.discover(Path(args.vendor) if args.vendor else None)
    _echo(f"FBX 导出器: {exp.kind}" + (f" @ {exp.path}" if exp.path else " （未找到）"))
    for n in exp.notes:
        _echo(f"  - {n}")
    try:
        import UnityPy  # noqa: F401
        _echo("UnityPy:    已安装")
    except Exception:
        _echo("UnityPy:    未安装（pip install UnityPy）")
    return 0 if exp.available else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="urecon",
        description="Unity 工程逆向学习流水线的编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  urecon init targets/foo --source /games/Foo\n"
               "  urecon fingerprint targets/foo\n"
               "  urecon inventory targets/foo\n"
               "  urecon extract   targets/foo --format fbx\n"
               "  urecon plan targets/foo\n"
               "  urecon report targets/foo\n"
               "  urecon compare targets/*/urecon.json\n",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="建立目标工作区")
    s.add_argument("workspace")
    s.add_argument("--source", required=True, help="游戏目录或 APK")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("fingerprint", help="识别版本/后端/框架/保护")
    s.add_argument("target", help="工作区目录或游戏目录/APK")
    s.add_argument("--json", action="store_true", help="输出 JSON")
    s.add_argument("--fast", action="store_true", help="跳过二进制字符串扫描")
    s.add_argument("--save", action="store_true", help="即使不在工作区里也写盘")
    s.set_defaults(func=cmd_fingerprint)

    s = sub.add_parser("inventory", help="清点资源容器与对象")
    s.add_argument("target")
    s.add_argument("-o", "--output", help="输出目录")
    s.add_argument("--max-containers", type=int, default=400)
    s.add_argument("--max-objects", type=int, default=200_000)
    s.add_argument("--unity-version", help="手动指定 UnityPy 的 fallback 版本，如 2022.3.16f1")
    s.set_defaults(func=cmd_inventory)

    s = sub.add_parser("plan", help="按指纹给出针对性的下一步")
    s.add_argument("target")
    s.add_argument("--fast", action="store_true")
    s.add_argument("--refresh", action="store_true", help="忽略缓存重新识别")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("report", help="生成 Markdown 报告")
    s.add_argument("target")
    s.add_argument("-o", "--output")
    s.add_argument("--title")
    s.add_argument("--fast", action="store_true")
    s.add_argument("--refresh", action="store_true")
    s.add_argument("--with-inventory", action="store_true", help="顺带重新清点资源")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("compare", help="多个目标横向对比")
    s.add_argument("states", nargs="+", help="若干 urecon.json / fingerprint.json")
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("extract", help="提取模型/动画并按人物·物品·场景分类")
    s.add_argument("target")
    s.add_argument("-o", "--output", help="输出目录，默认 <workspace>/extracted")
    s.add_argument("--format", choices=("fbx", "obj"), default="fbx",
                   help="fbx=可播放（需 AssetStudio）；obj=降级网格+动画摘要")
    s.add_argument("--exporter", choices=("auto", "assetstudio", "assetripper", "obj"),
                   default="auto", help="FBX 导出后端")
    s.add_argument("--classify-only", action="store_true", help="只做分类，不导出网格")
    s.add_argument("--max-containers", type=int, default=400)
    s.add_argument("--unity-version", help="UnityPy fallback 版本")
    s.add_argument("--vendor", help="外部工具所在目录，默认 ./vendor")
    s.set_defaults(func=cmd_extract)

    s = sub.add_parser("doctor", help="检查 FBX 导出器与 UnityPy 是否可用")
    s.add_argument("--vendor", help="外部工具所在目录")
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
