"""工作区布局：每个目标一个目录，原始文件只读，产物分目录存放。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

STATE_FILE = "urecon.json"
SUBDIRS = ("original", "extracted", "decompiled", "runtime", "notes", "repro")

GITIGNORE = """# 逆向产物不入库，见 docs/07-legal.md
*
!.gitignore
"""


@dataclass
class Workspace:
    root: Path
    source: Path

    @property
    def state_path(self) -> Path:
        return self.root / STATE_FILE

    def load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {}

    def save_state(self, data: dict) -> None:
        merged = self.load_state()
        merged.update(data)
        merged["source"] = str(self.source)
        self.state_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def dir(self, name: str) -> Path:
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p


def init(root: Path, source: Path) -> Workspace:
    root.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS:
        (root / d).mkdir(exist_ok=True)
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
    ws = Workspace(root, source.resolve())
    ws.save_state({"source": str(source.resolve())})
    return ws


def resolve(path: str | Path) -> Workspace:
    """既接受工作区目录（含 urecon.json），也接受原始游戏路径。"""
    p = Path(path).expanduser().resolve()
    state = p / STATE_FILE
    if p.is_dir() and state.exists():
        data = json.loads(state.read_text(encoding="utf-8"))
        src = Path(data.get("source", p))
        return Workspace(p, src if src.exists() else p)
    return Workspace(p, p)
