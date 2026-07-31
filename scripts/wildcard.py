"""词库模板解析。

支持三种语法：

    __path/name__   从 <wildcards_root>/path/name.txt 随机抽一行
    {a|b|c}         从若干候选中随机抽一个
    {2$$a|b|c}      抽 2 个，用 ", " 连接

嵌套可用：词库条目本身也可以包含上述语法，解析会递归展开。
"""

from __future__ import annotations

import random
import re
from pathlib import Path

WILDCARD_RE = re.compile(r"__([A-Za-z0-9_\-./]+)__")
# 只匹配不含嵌套花括号的最内层，循环解析即可自底向上展开
CHOICE_RE = re.compile(r"\{([^{}]*)\}")
COUNT_PREFIX_RE = re.compile(r"^(\d+)\$\$(.*)$", re.DOTALL)

MAX_DEPTH = 12


class WildcardError(RuntimeError):
    pass


def load_template(path: str | Path) -> str:
    """读取模板文件，去掉注释行，把多行合并为一行。"""
    raw = Path(path).read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
    return normalize(" ".join(ln.strip() for ln in lines))


def normalize(text: str) -> str:
    """收拾提示词里的空白与多余逗号，避免空标签影响 CLIP 编码。"""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)
    return text.strip().strip(",").strip()


class WildcardResolver:
    def __init__(self, root: str | Path, rng: random.Random | None = None) -> None:
        self.root = Path(root)
        self.rng = rng or random.Random()
        self._cache: dict[str, list[str]] = {}

    def entries(self, name: str) -> list[str]:
        if name in self._cache:
            return self._cache[name]
        path = self.root / f"{name}.txt"
        if not path.is_file():
            raise WildcardError(f"词库不存在: {path}")
        entries = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        if not entries:
            raise WildcardError(f"词库为空: {path}")
        self._cache[name] = entries
        return entries

    def names(self) -> list[str]:
        """列出所有可用词库名（相对路径，不含 .txt）。"""
        return sorted(
            p.relative_to(self.root).with_suffix("").as_posix()
            for p in self.root.rglob("*.txt")
        )

    def resolve(
        self,
        template: str,
        overrides: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str]]:
        """展开模板。

        overrides 把指定词库固定为给定值，用于控制变量扫描。
        返回 (提示词, 本次各词库实际抽到的值)。
        """
        overrides = overrides or {}
        picks: dict[str, str] = {}
        text = template

        for _ in range(MAX_DEPTH):
            expanded = self._expand_choices(text)
            expanded, changed = self._expand_wildcards(expanded, overrides, picks)
            if expanded == text and not changed:
                break
            text = expanded

        if WILDCARD_RE.search(text) or CHOICE_RE.search(text):
            raise WildcardError(
                f"展开层数超过 {MAX_DEPTH}，可能存在循环引用: {text[:120]}"
            )

        return normalize(text), picks

    def _expand_choices(self, text: str) -> str:
        while True:
            match = CHOICE_RE.search(text)
            if not match:
                return text
            text = text[: match.start()] + self._pick_choice(match.group(1)) + text[match.end() :]

    def _pick_choice(self, body: str) -> str:
        count = 1
        prefix = COUNT_PREFIX_RE.match(body)
        if prefix:
            count = max(1, int(prefix.group(1)))
            body = prefix.group(2)
        options = [opt.strip() for opt in body.split("|")]
        options = [opt for opt in options if opt]
        if not options:
            return ""
        count = min(count, len(options))
        return ", ".join(self.rng.sample(options, count))

    def _expand_wildcards(
        self,
        text: str,
        overrides: dict[str, str],
        picks: dict[str, str],
    ) -> tuple[str, bool]:
        changed = False
        out: list[str] = []
        cursor = 0
        for match in WILDCARD_RE.finditer(text):
            name = match.group(1)
            if name in overrides:
                value = overrides[name]
            else:
                value = self.rng.choice(self.entries(name))
            key = name if name not in picks else f"{name}#{sum(1 for k in picks if k.split('#')[0] == name) + 1}"
            picks[key] = value
            out.append(text[cursor : match.start()])
            out.append(value)
            cursor = match.end()
            changed = True
        out.append(text[cursor:])
        return "".join(out), changed
