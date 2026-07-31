"""读取角色设定集，作为 Spine 工作流的上游数据源。

设定集的 README 写明色号与头身比**只在 ``tools/palettes.json`` 中维护**，
所以这里绝不复制色值，一律从那份 JSON 现取。改设定集的配色，
重新 build 一次贴图就跟着变。

配色命名
--------
JSON 里的分组标签是中英混排的（"头发 Hair"、"羽翼 Wings（渐变顺序）"），
取其中的英文单词做键：``hair`` / ``eye`` / ``skin`` / ``costume`` / ``accent``
/ ``wings`` / ``gem`` / ``silver``。同组的第一个色板用键本身，其余依次加后缀，
例如灯莉的服装组给出 ``costume``（制服）、``costume_2``（制服影）、
``costume_3``（半纏）……概念文件再用 ``aliases`` 起可读的名字。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from spineforge.config import REPO_ROOT

BIBLE_PATH = REPO_ROOT / "tools" / "palettes.json"

_ASCII_WORD = re.compile(r"[A-Za-z]+")
_HEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*cm")
_HEADS = re.compile(r"(\d+(?:\.\d+)?)\s*头身")


class BibleError(ValueError):
    """设定集里缺东西或格式不对。"""


@dataclass(frozen=True)
class BibleCharacter:
    work: str
    key: str
    name: str
    subtitle: str
    accent: str
    height_cm: float
    heads: float
    silhouette: str
    palette: dict[str, str]
    # {配色键: 设定集里写的用途}，只用于文档和报错提示
    uses: dict[str, str] = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.work}/{self.key}"


def _group_key(label: str) -> str:
    match = _ASCII_WORD.search(label)
    if not match:
        raise BibleError(f"配色分组标签 {label!r} 里找不到英文单词，无法推出配色键")
    return match.group(0).lower()


def _parse_palette(groups: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    palette: dict[str, str] = {}
    uses: dict[str, str] = {}
    for group in groups:
        key = _group_key(group["label"])
        for i, swatch in enumerate(group["swatches"], start=1):
            name = key if i == 1 else f"{key}_{i}"
            palette[name] = swatch["hex"]
            uses[name] = swatch.get("use", "")
    return palette, uses


def _parse_metrics(character: dict, work: dict) -> tuple[float, float, str]:
    """身高与头身比从 ``subtitle`` 里取，剪影识别点从 ``proportions`` 里取。

    subtitle 是每个角色都有的（"156cm · 6.8 头身"），而 ``proportions``
    只有部分企划写了，所以前者当主来源。
    """
    subtitle = character.get("subtitle", "")
    height = _HEIGHT.search(subtitle)
    heads = _HEADS.search(subtitle)
    if not height or not heads:
        raise BibleError(
            f"角色 {character.get('name')!r} 的 subtitle 里读不到身高与头身比："
            f"{subtitle!r}（期望形如 '156cm · 6.8 头身'）"
        )

    silhouette = ""
    display_name = character.get("name", "")
    for row in work.get("proportions", ()):
        if row.get("name") and row["name"] in display_name:
            silhouette = row.get("silhouette", "")
            break
    return float(height.group(1)), float(heads.group(1)), silhouette


def load_bible(path: Path | None = None) -> dict[str, BibleCharacter]:
    """加载全部角色，键为 ``<企划>/<角色>``。"""
    src = Path(path) if path else BIBLE_PATH
    if not src.is_file():
        raise BibleError(f"找不到角色设定集数据源 {src}")
    data = json.loads(src.read_text(encoding="utf-8"))

    out: dict[str, BibleCharacter] = {}
    for work_key, work in data["works"].items():
        for char_key, character in work.get("characters", {}).items():
            palette, uses = _parse_palette(character["groups"])
            height, heads, silhouette = _parse_metrics(character, work)
            entry = BibleCharacter(
                work=work_key,
                key=char_key,
                name=character.get("name", char_key),
                subtitle=character.get("subtitle", ""),
                accent=character.get("accent", ""),
                height_cm=height,
                heads=heads,
                silhouette=silhouette,
                palette=palette,
                uses=uses,
            )
            out[entry.ref] = entry
    return out


def get_character(ref: str, path: Path | None = None) -> BibleCharacter:
    bible = load_bible(path)
    if ref not in bible:
        raise BibleError(f"设定集里没有 {ref!r}，已收录：{sorted(bible)}")
    return bible[ref]


def derive_rig(heads: float, height_cm: float, px_per_cm: float) -> dict[str, float]:
    """由头身比推出骨架比例。

    长度一律以**头长**为单位（``unit`` 就是一个头长折合多少像素），
    这和美术画头身比对照图时的思路一致：改头身比，腿长和手臂长跟着变，
    5.5 头身的忍和 8.0 头身的伊卡洛斯会得到明显不同的骨架。

    躯干链固定占 3.1 个头长（头 1.0 + 颈 0.25 + 胸 0.85 + 腰腹 1.0），
    剩下的全归腿，于是 ``heads`` 越大腿越长——这正是头身比的定义。
    """
    if heads <= 3.4:
        raise BibleError(f"头身比 {heads} 太小，躯干链就占掉 3.1 个头长了")

    leg = heads - 3.1
    # 手臂总长（肩到腕）随头身比线性增长：8 头身约 3 个头长，5.5 头身约 2 个
    arm = 0.375 * heads

    return {
        "unit": height_cm * px_per_cm / heads,
        "hip_height": leg,
        "torso": 1.0,
        "chest": 0.85,
        "neck": 0.25,
        "head": 1.0,
        "thigh": leg * 0.50,
        "shin": leg * 0.42,
        "foot": 0.30,
        "upper_arm": arm * 0.44,
        "lower_arm": arm * 0.40,
        "hand": arm * 0.16,
        "shoulder_span": 0.85 + 0.05 * (heads - 5.5),
        "hip_span": 0.50 + 0.03 * (heads - 5.5),
        "tail": 0.80,
        "wing": 2.00,
    }
