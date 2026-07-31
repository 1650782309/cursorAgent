"""命令行入口：``python -m spineforge <子命令>``。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spineforge import pipeline
from spineforge.concept import ConceptError, list_concepts, load_concept
from spineforge.config import DEFAULT, Config


def log(msg: str) -> None:
    print(msg, flush=True)


def _cfg(args: argparse.Namespace) -> Config:
    cfg = Config()
    if getattr(args, "build_dir", None):
        cfg.build_dir = args.build_dir
    if getattr(args, "downscale", None):
        cfg.downscale = args.downscale
    return cfg


# ---------------------------------------------------------------- 子命令实现
def cmd_list(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    for c in list_concepts(cfg):
        outfits = "、".join(c.outfits) or "（无）"
        log(f"{c.id:<14} {c.name:<8} {c.archetype:<8} "
            f"部件 {len(c.parts):>2}  动画 {len(c.animations)}  换装：{outfits}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from spineforge import doctor

    cfg = _cfg(args)
    log("spineforge 环境自检")
    checks = doctor.run(cfg, probe_sd=args.sd)
    text, code = doctor.report(checks, probe_sd=args.sd)
    log(text)
    return code


def cmd_show(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    c = load_concept(args.concept, cfg)
    log(f"{c.id}  {c.name}（{c.archetype}）")
    if c.summary:
        log(f"  {c.summary}")
    log(f"  画布 {c.canvas.width}x{c.canvas.height}，原点 ({c.canvas.origin_x}, {c.canvas.origin_y})")
    log(f"  动画 {', '.join(c.animations)}")
    log(f"  部件 {len(c.parts)} 个，其中需重绘 {sum(1 for p in c.parts if p.redraw)} 个")
    for p in c.draw_order():
        flag = "重绘" if p.redraw else "保形"
        log(f"    {p.order:>2} {p.name:<14} {p.bone:<14} {p.shape:<8} {flag}  "
            f"{p.pixel_size[0]}x{p.pixel_size[1]}px  标签 {','.join(p.tags) or '-'}")
    for name, o in c.outfits.items():
        log(f"  换装 {name}：targets={list(o.targets) or '全部'}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    for c in _targets(args, cfg):
        log(f"== build {c.id} ==")
        r = pipeline.build(c, cfg, log)
        log(f"完成：{r.images} 张贴图，骨架 {r.skeleton_path}")
    return 0


def cmd_preprocess(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    c = load_concept(args.concept, cfg)
    outfit = c.outfit(args.outfit) if args.outfit else None
    log(f"== preprocess {c.id} / {args.outfit or '全部可重绘部件'} ==")
    pipeline.preprocess(c, outfit, cfg, log)
    return 0


def cmd_reskin(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    c = load_concept(args.concept, cfg)
    outfit = c.outfit(args.outfit)
    log(f"== reskin {c.id} / {outfit.name} ==")
    r = pipeline.reskin(c, outfit, args.seed, args.backend, cfg, log,
                        keep_steps=not args.no_steps)
    log(f"完成：{r.written_texels} 纹素回写，耗时 {r.seconds}s -> {r.out_dir}")
    if args.preview:
        images = r.out_dir / "images"
        for anim in c.animations:
            pipeline.preview(c, anim, images, r.out_dir / "preview" / f"{anim}.gif", cfg, log=log)
        pipeline.contact_sheet(c, images, r.out_dir / "preview" / "sheet.png", cfg)
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    c = load_concept(args.concept, cfg)
    images = Path(args.images) if args.images else cfg.images_dir(c.id)
    out_dir = Path(args.out) if args.out else cfg.character_dir(c.id) / "preview"
    anims = [args.animation] if args.animation else list(c.animations)
    for anim in anims:
        pipeline.preview(c, anim, images, out_dir / f"{anim}.gif", cfg, fps=args.fps, log=log)
    pipeline.contact_sheet(c, images, out_dir / "sheet.png", cfg)
    log(f"对照图 -> {out_dir / 'sheet.png'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """build + preprocess + reskin + preview 一条龙。"""
    cfg = _cfg(args)
    c = load_concept(args.concept, cfg)
    outfit = c.outfit(args.outfit)
    log(f"== build {c.id} ==")
    pipeline.build(c, cfg, log)
    log(f"== preprocess {c.id} / {outfit.name} ==")
    pipeline.ensure_preprocess(c, outfit, cfg, log, force=True)
    log(f"== reskin {c.id} / {outfit.name} ==")
    r = pipeline.reskin(c, outfit, args.seed, args.backend, cfg, log)
    images = r.out_dir / "images"
    for anim in c.animations:
        pipeline.preview(c, anim, images, r.out_dir / "preview" / f"{anim}.gif", cfg, log=log)
    pipeline.contact_sheet(c, images, r.out_dir / "preview" / "sheet.png", cfg)
    log(f"完成 -> {r.out_dir}")
    return 0


def _targets(args: argparse.Namespace, cfg: Config) -> list:
    if args.concept in (None, "all"):
        return list_concepts(cfg)
    return [load_concept(args.concept, cfg)]


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spineforge",
        description="由角色概念库驱动的 Spine 动画自动生成与 SD 换装工作流",
    )
    p.add_argument("--build-dir", help=f"产物根目录（默认 {DEFAULT.build_dir}）")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("doctor", help="安装自检：依赖、设定集、画布对齐、SD 连通性")
    s.add_argument("--sd", action="store_true", help="顺带体检 Stable Diffusion WebUI")
    s.add_argument("--downscale", type=int)
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("list", help="列出角色概念库")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="查看单个角色的部件与换装预设")
    s.add_argument("concept")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("build", help="生成贴图 + 骨架 + 动画")
    s.add_argument("concept", nargs="?", default="all")
    s.add_argument("--downscale", type=int)
    s.set_defaults(func=cmd_build)

    s = sub.add_parser("preprocess", help="选关键姿势并生成 UV / mask / ctrl")
    s.add_argument("concept")
    s.add_argument("--outfit")
    s.add_argument("--downscale", type=int)
    s.set_defaults(func=cmd_preprocess)

    s = sub.add_parser("reskin", help="用 SD 给 Spine 模型换装")
    s.add_argument("concept")
    s.add_argument("outfit")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--backend", choices=("mock", "webui"), default="mock")
    s.add_argument("--downscale", type=int)
    s.add_argument("--preview", action="store_true", help="换装后顺便渲染 GIF 预览")
    s.add_argument("--no-steps", action="store_true", help="不保留逐姿势中间图")
    s.set_defaults(func=cmd_reskin)

    s = sub.add_parser("preview", help="渲染动画 GIF 与关键姿势对照图")
    s.add_argument("concept")
    s.add_argument("--animation")
    s.add_argument("--images", help="贴图目录，默认用原始贴图")
    s.add_argument("--out")
    s.add_argument("--fps", type=int, default=24)
    s.set_defaults(func=cmd_preview)

    s = sub.add_parser("run", help="build + preprocess + reskin + preview")
    s.add_argument("concept")
    s.add_argument("outfit")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--backend", choices=("mock", "webui"), default="mock")
    s.add_argument("--downscale", type=int)
    s.set_defaults(func=cmd_run)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConceptError as exc:
        print(f"概念库错误：{exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
