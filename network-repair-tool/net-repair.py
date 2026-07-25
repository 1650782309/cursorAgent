#!/usr/bin/env python3
"""网络状态检测与修复工具 — 入口脚本。"""

import sys
from pathlib import Path

# 允许直接运行此脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))

from network_tool.cli import main

if __name__ == "__main__":
    sys.exit(main())
