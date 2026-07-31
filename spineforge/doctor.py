"""安装自检。

本地部署最容易卡住的不是 Python 依赖，而是 Stable Diffusion 那一侧：
API 没开、ControlNet 没装、模型名和配置对不上。这些问题在真正出图时才会暴露，
而且报错常常似是而非。所以这里把能提前查的都查一遍，并且明说哪些查不了。

    spineforge doctor          只查本地环境（不碰网络）
    spineforge doctor --sd     顺带体检 Stable Diffusion WebUI
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from spineforge.config import Config

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class Check:
    status: str
    title: str
    detail: str = ""
    hint: str = ""


MIN_PYTHON = (3, 10)
REQUIRED = ("numpy", "PIL", "yaml", "requests")
# 装包名和 import 名对不上的，报错时要提示前者
PACKAGE_OF = {"PIL": "pillow", "yaml": "pyyaml"}


def check_python() -> Check:
    v = sys.version_info
    got = f"{v.major}.{v.minor}.{v.micro} ({platform.python_implementation()})"
    if (v.major, v.minor) < MIN_PYTHON:
        return Check(FAIL, "Python 版本", got,
                     f"需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 以上，代码里用了新版类型标注语法")
    return Check(OK, "Python 版本", got)


def check_dependencies() -> list[Check]:
    out: list[Check] = []
    for name in REQUIRED:
        try:
            module = __import__(name)
        except ImportError:
            pkg = PACKAGE_OF.get(name, name)
            out.append(Check(FAIL, f"依赖 {pkg}", "未安装",
                             "pip install -r requirements.txt"))
            continue
        version = getattr(module, "__version__", "?")
        out.append(Check(OK, f"依赖 {PACKAGE_OF.get(name, name)}", version))
    return out


def check_data(cfg: Config) -> list[Check]:
    """确认角色设定集与概念库都在。它们是数据，不随包安装。"""
    from spineforge.bible import BIBLE_PATH

    out: list[Check] = []
    if BIBLE_PATH.is_file():
        out.append(Check(OK, "角色设定集", str(BIBLE_PATH)))
    else:
        out.append(Check(FAIL, "角色设定集", f"找不到 {BIBLE_PATH}",
                         "请在克隆出来的仓库目录里运行，或改用 pip install -e ."))
        return out

    try:
        from spineforge.concept import list_concepts

        concepts = list_concepts(cfg)
    except Exception as exc:  # 概念文件写坏了也算环境问题，要报出来
        out.append(Check(FAIL, "概念库", f"解析失败：{exc}"))
        return out

    if not concepts:
        out.append(Check(FAIL, "概念库", f"{cfg.concepts_dir} 下没有概念文件"))
        return out
    out.append(Check(OK, "概念库", f"{len(concepts)} 个角色："
                                   + "、".join(c.id for c in concepts)))

    # 画布必须能被 8*downscale 整除，否则 SD 会自行 padding，回写会整体错位
    unit = 8 * cfg.downscale
    bad = [f"{c.id} {c.canvas.width}x{c.canvas.height}" for c in concepts
           if c.canvas.width % unit or c.canvas.height % unit]
    if bad:
        out.append(Check(WARN, f"画布对齐（downscale={cfg.downscale}）",
                         "、".join(bad),
                         f"画布宽高需为 {unit} 的倍数，否则 SD 出图与遮罩会错位"))
    else:
        out.append(Check(OK, f"画布对齐（downscale={cfg.downscale}）", "全部合规"))
    return out


def check_writable(cfg: Config) -> Check:
    path = Path(cfg.build_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check(FAIL, "产物目录可写", f"{path}：{exc}",
                     "换个目录：SPINEFORGE_BUILD_DIR=/path/to/out")
    return Check(OK, "产物目录可写", str(path))


def check_stable_diffusion(cfg: Config) -> list[Check]:
    """体检 SD WebUI。查不通不代表装错了——可能只是没启动。"""
    import requests

    base = f"http://{cfg.sd_host}:{cfg.sd_port}"
    out: list[Check] = []

    try:
        r = requests.get(f"{base}/sdapi/v1/sd-models", timeout=5)
        r.raise_for_status()
        models = [m.get("title", "") for m in r.json()]
    except Exception as exc:
        out.append(Check(FAIL, "SD WebUI API", f"{base} 连不上：{type(exc).__name__}",
                         "启动 WebUI 时要带 --api；换机器用 SPINEFORGE_SD_HOST/PORT 指定"))
        return out
    out.append(Check(OK, "SD WebUI API", f"{base}，{len(models)} 个模型"))

    if cfg.sd_model:
        if any(cfg.sd_model in m for m in models):
            out.append(Check(OK, "SD 模型", cfg.sd_model))
        else:
            out.append(Check(FAIL, "SD 模型", f"WebUI 里没有 {cfg.sd_model}",
                             "名字要和 WebUI 下拉框里完全一致（含 [hash]）"))
    else:
        out.append(Check(WARN, "SD 模型", "未指定，将沿用 WebUI 当前模型",
                         "建议设 SPINEFORGE_SD_MODEL 固定下来，否则出图不可复现"))

    try:
        r = requests.get(f"{base}/controlnet/model_list", timeout=5)
        r.raise_for_status()
        cn_models = r.json().get("model_list", [])
    except Exception:
        out.append(Check(FAIL, "ControlNet 扩展", "没有 /controlnet 接口",
                         "装 sd-webui-controlnet 扩展并重启 WebUI"))
        return out
    out.append(Check(OK, "ControlNet 扩展", f"{len(cn_models)} 个控制模型"))

    if any(cfg.controlnet_canny_model in m for m in cn_models):
        out.append(Check(OK, "ControlNet canny 模型", cfg.controlnet_canny_model))
    else:
        sample = "、".join(cn_models[:3]) or "（空）"
        out.append(Check(FAIL, "ControlNet canny 模型",
                         f"没有 {cfg.controlnet_canny_model}",
                         f"用 SPINEFORGE_CONTROLNET_CANNY_MODEL 改成已有的，例如：{sample}"))

    # 降采样出图后要放大回画布尺寸，缺超分模型会退回 Lanczos，只是糊一点
    if cfg.downscale > 1:
        try:
            r = requests.get(f"{base}/sdapi/v1/upscalers", timeout=5)
            names = [u.get("name", "") for u in r.json()]
            if any("Anime6B" in n for n in names):
                out.append(Check(OK, "超分模型", "R-ESRGAN 4x+ Anime6B"))
            else:
                out.append(Check(WARN, "超分模型", "没有 R-ESRGAN 4x+ Anime6B",
                                 "会退回 Lanczos 放大，不影响对齐，只是细节softer"))
        except Exception:
            pass
    return out


def run(cfg: Config, probe_sd: bool = False) -> list[Check]:
    checks = [check_python(), *check_dependencies()]
    if all(c.status != FAIL for c in checks):
        checks += check_data(cfg)
        checks.append(check_writable(cfg))
    if probe_sd:
        checks += check_stable_diffusion(cfg)
    return checks


def display_width(text: str) -> int:
    """终端里的显示宽度。中日韩字符占两列，用 len() 对齐会歪。"""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def report(checks: list[Check], probe_sd: bool) -> tuple[str, int]:
    """把结果排版成文本，并返回建议的退出码。"""
    width = max(display_width(c.title) for c in checks)
    lines = []
    for c in checks:
        pad = " " * (width - display_width(c.title))
        lines.append(f"  [{c.status:<4}] {c.title}{pad}  {c.detail}")
        if c.hint and c.status != OK:
            lines.append(f"         {' ' * width}  -> {c.hint}")

    failed = sum(c.status == FAIL for c in checks)
    warned = sum(c.status == WARN for c in checks)
    lines.append("")
    if failed:
        lines.append(f"{failed} 项不通过，{warned} 项提醒。按上面的 -> 处理后重跑。")
    elif warned:
        lines.append(f"全部通过，{warned} 项提醒。可以开始跑了：spineforge run akari field_work")
    else:
        lines.append("全部通过。可以开始跑了：spineforge run akari field_work")
    if not probe_sd:
        lines.append("离线 mock 后端到此即可；要接 Stable Diffusion 再跑 spineforge doctor --sd")
    return "\n".join(lines), (1 if failed else 0)
