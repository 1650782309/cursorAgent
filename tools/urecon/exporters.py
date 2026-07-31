"""可播放 FBX 的外部导出器编排。

UnityPy 不能导出带动画的 FBX。真正可播放的 FBX 依赖：
  - AssetStudio / AssetStudioMod CLI（首选，直接出 FBX）
  - AssetRipper CLI（导出 Unity 工程，再批处理导 FBX）

查找顺序：
  1. 环境变量 URECON_FBX_EXPORTER / URECON_ASSETSTUDIO / URECON_ASSETRIPPER
  2. 仓库 vendor/ 下的常见目录
  3. PATH 里的可执行文件名
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ASSETSTUDIO_NAMES = (
    "AssetStudio.CLI.exe", "AssetStudio.CLI", "AssetStudioCLI.exe", "AssetStudioCLI",
    "AssetStudio.exe", "AssetStudio",
)
ASSETRIPPER_NAMES = (
    "AssetRipper.CLI.exe", "AssetRipper.CLI", "AssetRipper.exe", "AssetRipper",
    "AssetRipper.SourceGenerated.exe",
)


@dataclass
class Exporter:
    kind: str                 # assetstudio / assetripper / none
    path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.kind != "none" and self.path is not None and self.path.exists()


def _looks_like(path: Path, names: tuple[str, ...]) -> bool:
    return path.is_file() and path.name in names


def _walk_find(root: Path, names: tuple[str, ...], depth: int = 3) -> Path | None:
    if not root.exists():
        return None
    target = {n.lower() for n in names}
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).resolve().relative_to(root)
        if len(rel.parts) > depth:
            dirnames.clear()
            continue
        for fn in filenames:
            if fn.lower() in target:
                return Path(dirpath) / fn
    return None


def discover(vendor_dir: Path | None = None) -> Exporter:
    notes: list[str] = []

    for env_key, kind in (
        ("URECON_FBX_EXPORTER", "auto"),
        ("URECON_ASSETSTUDIO", "assetstudio"),
        ("URECON_ASSETRIPPER", "assetripper"),
    ):
        raw = os.environ.get(env_key)
        if not raw:
            continue
        p = Path(raw).expanduser()
        if not p.exists():
            notes.append(f"{env_key}={raw} 不存在，已忽略")
            continue
        if kind == "auto":
            kind = "assetstudio" if "studio" in p.name.lower() else (
                "assetripper" if "ripper" in p.name.lower() else "assetstudio"
            )
        return Exporter(kind=kind, path=p, notes=notes)

    search_roots: list[Path] = []
    if vendor_dir:
        search_roots.append(vendor_dir)
    # 从包位置推断仓库 vendor/
    here = Path(__file__).resolve()
    search_roots.append(here.parents[2] / "vendor")
    search_roots.append(Path.cwd() / "vendor")

    for root in search_roots:
        hit = _walk_find(root, ASSETSTUDIO_NAMES)
        if hit:
            return Exporter("assetstudio", hit, notes)
        hit = _walk_find(root, ASSETRIPPER_NAMES)
        if hit:
            return Exporter("assetripper", hit, notes)

    for name in ASSETSTUDIO_NAMES:
        found = shutil.which(name)
        if found:
            return Exporter("assetstudio", Path(found), notes)
    for name in ASSETRIPPER_NAMES:
        found = shutil.which(name)
        if found:
            return Exporter("assetripper", Path(found), notes)

    notes.append(
        "未找到 AssetStudio / AssetRipper。可播放 FBX 需要外部工具："
        "设置 URECON_ASSETSTUDIO，或运行 scripts/fetch_tools.sh 装到 vendor/"
    )
    return Exporter("none", None, notes)


def run_assetstudio(
    exe: Path,
    source: Path,
    output: Path,
    *,
    types: str = "Mesh,Animator,AnimationClip,Texture2D,Sprite",
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """调用 AssetStudio CLI。不同 fork 参数略有差异，按常见顺序尝试。"""
    output.mkdir(parents=True, exist_ok=True)
    attempts = [
        # AssetStudioMod / aelurum CLI
        [str(exe), str(source), "-o", str(output), "-t", types, "-f", "fbx"],
        [str(exe), str(source), "--output", str(output), "--types", types, "--format", "fbx"],
        [str(exe), "-i", str(source), "-o", str(output), "-t", types],
        # 无 CLI 的 GUI 版无法批处理，会失败并被上层捕获
        [str(exe), str(source), str(output)],
    ]
    last: subprocess.CompletedProcess | None = None
    for cmd in attempts:
        try:
            last = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = subprocess.CompletedProcess(cmd, 127, "", str(exc))
            continue
        if last.returncode == 0:
            return last
        # 参数不被识别时试下一个；真正的导出错误也返回给调用方看
        err = (last.stderr or last.stdout or "").lower()
        if "unknown" in err or "usage" in err or "unrecognized" in err:
            continue
        return last
    assert last is not None
    return last


def run_assetripper(
    exe: Path,
    source: Path,
    output: Path,
    *,
    timeout: int = 7200,
) -> subprocess.CompletedProcess:
    """AssetRipper 导出的是可打开的 Unity 工程，不是直接 FBX。

    调用方应把工程路径记入清单，并提示用 Unity FBX Exporter 做第二步；
    同时我们会把工程里的模型资源按分类规则整理软链接/清单。
    """
    output.mkdir(parents=True, exist_ok=True)
    attempts = [
        [str(exe), str(source), "-o", str(output)],
        [str(exe), "--input", str(source), "--output", str(output)],
        [str(exe), str(source), str(output)],
    ]
    last: subprocess.CompletedProcess | None = None
    for cmd in attempts:
        try:
            last = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = subprocess.CompletedProcess(cmd, 127, "", str(exc))
            continue
        if last.returncode == 0:
            return last
        err = (last.stderr or last.stdout or "").lower()
        if "unknown" in err or "usage" in err or "unrecognized" in err:
            continue
        return last
    assert last is not None
    return last
