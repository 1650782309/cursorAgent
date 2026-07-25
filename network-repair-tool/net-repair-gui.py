#!/usr/bin/env python3
"""网络修复工具 — 图形界面启动器（可双击运行）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from network_tool.gui import run_gui

if __name__ == "__main__":
    run_gui()
