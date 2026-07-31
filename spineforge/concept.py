"""角色概念库的加载与校验。

字段含义见 ``concepts/_schema.md``。这里只做结构化 + 早失败校验，
不做任何绘制或路径推导。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from spineforge.bible import BibleCharacter, derive_rig, get_character
from spineforge.config import DEFAULT, Config

ID_RE = re.compile(r"^[a-z0-9_]+$")
SHAPES = {"capsule", "ellipse", "blade", "bell", "plate", "cape",
          "cone", "wing", "ring"}
# 贴图四周留白，给描边和抗锯齿边缘留位置。与 partgen.PAD 保持一致。
PART_PADDING = 2


class ConceptError(ValueError):
    """概念文件不合法。消息里总是带上出错的角色 id 与字段。"""


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    origin_x: float
    origin_y: float
    # 像素/厘米。设定集给的是厘米身高，靠它换算成画布尺寸，
    # 于是 178cm 的墨在画面上确实比 142cm 的忍高一头。
    px_per_cm: float = 2.4


@dataclass(frozen=True)
class Part:
    name: str
    bone: str
    shape: str
    size: tuple[float, float]
    color: str
    order: int
    offset: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    shade: float = 0.25
    # 左右对称的部件（羽翼、耳朵）只画一侧的贴图，另一侧翻过来用
    mirror: bool = False
    redraw: bool = True
    tags: tuple[str, ...] = ()
    # 贴图分辨率，由 size * rig.unit 推出，加载概念时填入。
    pixel_size: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class Outfit:
    name: str
    prompt: str
    negative_prompt: str = ""
    targets: tuple[str, ...] = ()
    palette_hint: dict[str, str] = field(default_factory=dict)
    denoising_strength: float | None = None


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    archetype: str
    summary: str
    canvas: Canvas
    palette: dict[str, str]
    rig: dict[str, float]
    parts: tuple[Part, ...]
    animations: tuple[str, ...]
    groups: tuple[tuple[str, ...], ...]
    outfits: dict[str, Outfit]
    source_path: Path | None = None
    # 来自角色设定集的原始条目，None 表示这份概念自带配色（主要用于测试）
    bible: BibleCharacter | None = None

    def part(self, name: str) -> Part:
        for p in self.parts:
            if p.name == name:
                return p
        raise KeyError(name)

    def draw_order(self) -> list[Part]:
        """按 ``order`` 升序返回部件，即从最底层到最顶层的绘制顺序。"""
        return sorted(self.parts, key=lambda p: p.order)

    def redraw_parts(self, outfit: Outfit | None = None) -> list[Part]:
        """本次换装真正需要 SD 重绘的部件。

        部件自身 ``redraw: false`` 时永远跳过；outfit 指定了 ``targets`` 时，
        还要求部件至少命中一个目标标签。
        """
        out = []
        for p in self.draw_order():
            if not p.redraw:
                continue
            if outfit and outfit.targets and not (set(p.tags) & set(outfit.targets)):
                continue
            out.append(p)
        return out

    def outfit(self, name: str) -> Outfit:
        if name not in self.outfits:
            raise ConceptError(
                f"[{self.id}] 没有名为 {name!r} 的换装预设，可选：{sorted(self.outfits)}"
            )
        return self.outfits[name]

    def rgb(self, color_name: str) -> tuple[int, int, int]:
        return hex_to_rgb(self.palette[color_name])


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) != 6:
        raise ConceptError(f"颜色必须是 #RRGGBB，收到 {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _req(data: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in data:
        raise ConceptError(f"{ctx} 缺少必填字段 {key!r}")
    return data[key]


def _num(value: Any, rig: dict[str, float], ctx: str) -> float:
    """把尺寸/偏移解析成头长倍数。

    除了直接写数字，还能引用骨骼长度，例如大腿贴图写 ``"thigh"``、
    贴图中心写 ``"thigh*0.5"``、外套盖住腰腹加胸腔写 ``"torso+chest"``。
    头身比不同的角色腿长本来就不同，引用骨骼长度就不用为每个角色重算一遍。
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ConceptError(f"{ctx} 应为数字或骨骼长度表达式，收到 {value!r}")

    total = 0.0
    for term in value.split("+"):
        term = term.strip()
        if not term:
            continue
        key, _, factor = term.partition("*")
        key = key.strip()
        scale = float(factor) if factor.strip() else 1.0
        try:
            total += float(key) * scale
        except ValueError:
            if key not in rig:
                raise ConceptError(
                    f"{ctx} 引用了未知的骨骼长度 {key!r}，可用：{sorted(rig)}"
                ) from None
            total += rig[key] * scale
    return total


def _pair(value: Any, rig: dict[str, float], ctx: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ConceptError(f"{ctx} 应为 [x, y] 两项，收到 {value!r}")
    return _num(value[0], rig, f"{ctx}[0]"), _num(value[1], rig, f"{ctx}[1]")


def parse_concept(data: dict[str, Any], source_path: Path | None = None,
                  bible_path: Path | None = None) -> Concept:
    cid = str(_req(data, "id", "概念文件"))
    if not ID_RE.match(cid):
        raise ConceptError(f"id {cid!r} 只能包含小写字母、数字和下划线")
    ctx = f"[{cid}]"

    canvas_raw = _req(data, "canvas", ctx)
    canvas = Canvas(
        width=int(_req(canvas_raw, "width", f"{ctx}.canvas")),
        height=int(_req(canvas_raw, "height", f"{ctx}.canvas")),
        origin_x=float(canvas_raw.get("origin_x", canvas_raw["width"] / 2)),
        origin_y=float(canvas_raw.get("origin_y", canvas_raw["height"] * 0.9)),
        px_per_cm=float(canvas_raw.get("px_per_cm", 2.4)),
    )

    # 引用了设定集就从设定集取配色与头身比，概念文件里不再重复色号。
    bible: BibleCharacter | None = None
    if "bible" in data:
        bible = get_character(str(data["bible"]), bible_path)
        palette = dict(bible.palette)
        rig = derive_rig(bible.heads, bible.height_cm, canvas.px_per_cm)
    else:
        palette = {}
        rig = {}

    # `palette` 用于补充设定集里没有的颜色（例如灵体雾这类特效色）
    for k, v in (data.get("palette") or {}).items():
        palette[str(k)] = str(v)
    if not palette:
        raise ConceptError(f"{ctx} 需要 bible 引用或 palette 字段之一来提供配色")
    for k, v in palette.items():
        hex_to_rgb(v)  # 早失败

    # `aliases` 给设定集的机械命名起可读的名字：hanten -> costume_3
    for alias, target in (data.get("aliases") or {}).items():
        if target not in palette:
            hint = ""
            if bible:
                hint = "，设定集给出的配色键：" + "、".join(
                    f"{k}({bible.uses.get(k, '')})" for k in bible.palette
                )
            raise ConceptError(f"{ctx}.aliases[{alias}] 指向不存在的配色 {target!r}{hint}")
        palette[str(alias)] = palette[target]

    rig.update({str(k): float(v) for k, v in (data.get("rig") or {}).items()})
    if rig.get("unit", 0) <= 0:
        raise ConceptError(f"{ctx}.rig.unit 必须为正数")

    parts: list[Part] = []
    seen: set[str] = set()
    for raw in _req(data, "parts", ctx):
        pname = str(_req(raw, "name", f"{ctx}.parts[]"))
        pctx = f"{ctx}.parts[{pname}]"
        if pname in seen:
            raise ConceptError(f"{pctx} 部件名重复")
        seen.add(pname)
        shape = str(_req(raw, "shape", pctx))
        if shape not in SHAPES:
            raise ConceptError(f"{pctx}.shape={shape!r} 不支持，可选：{sorted(SHAPES)}")
        color = str(_req(raw, "color", pctx))
        if color not in palette:
            raise ConceptError(f"{pctx}.color={color!r} 不在 palette 中")
        size = _pair(_req(raw, "size", pctx), rig, f"{pctx}.size")
        if size[0] <= 0 or size[1] <= 0:
            raise ConceptError(f"{pctx}.size 必须为正数")
        unit = rig["unit"]
        pad = 2 * PART_PADDING
        parts.append(
            Part(
                pixel_size=(
                    max(int(round(size[0] * unit)) + pad, 4),
                    max(int(round(size[1] * unit)) + pad, 4),
                ),
                name=pname,
                bone=str(_req(raw, "bone", pctx)),
                shape=shape,
                size=size,
                color=color,
                order=int(_req(raw, "order", pctx)),
                offset=_pair(raw.get("offset", [0, 0]), rig, f"{pctx}.offset"),
                rotation=float(raw.get("rotation", 0.0)),
                shade=float(raw.get("shade", 0.25)),
                mirror=bool(raw.get("mirror", False)),
                redraw=bool(raw.get("redraw", True)),
                tags=tuple(str(t) for t in raw.get("tags", ())),
            )
        )
    if not parts:
        raise ConceptError(f"{ctx}.parts 不能为空")

    orders = [p.order for p in parts]
    if len(set(orders)) != len(orders):
        dupes = sorted({o for o in orders if orders.count(o) > 1})
        raise ConceptError(f"{ctx}.parts 的 order 必须唯一，重复值：{dupes}")

    groups: list[tuple[str, ...]] = []
    for g in data.get("groups", ()):
        for member in g:
            if member not in seen:
                raise ConceptError(f"{ctx}.groups 引用了不存在的部件 {member!r}")
        groups.append(tuple(str(m) for m in g))

    outfits: dict[str, Outfit] = {}
    for oname, raw in (data.get("outfits") or {}).items():
        octx = f"{ctx}.outfits[{oname}]"
        hints = {str(k): str(v) for k, v in (raw.get("palette_hint") or {}).items()}
        for k, v in hints.items():
            if k not in palette:
                raise ConceptError(f"{octx}.palette_hint 引用了不存在的颜色 {k!r}")
            hex_to_rgb(v)
        ds = raw.get("denoising_strength")
        outfits[str(oname)] = Outfit(
            name=str(oname),
            prompt=str(_req(raw, "prompt", octx)).strip(),
            negative_prompt=str(raw.get("negative_prompt", "")).strip(),
            targets=tuple(str(t) for t in raw.get("targets", ())),
            palette_hint=hints,
            denoising_strength=float(ds) if ds is not None else None,
        )

    return Concept(
        id=cid,
        name=str(data.get("name") or (bible.name if bible else cid)),
        archetype=str(data.get("archetype", "")),
        summary=str(data.get("summary") or (bible.subtitle if bible else "")),
        canvas=canvas,
        palette=palette,
        rig=rig,
        parts=tuple(parts),
        animations=tuple(str(a) for a in data.get("animations", ("idle",))),
        groups=tuple(groups),
        outfits=outfits,
        source_path=source_path,
        bible=bible,
    )


def load_concept(concept_id: str, cfg: Config = DEFAULT) -> Concept:
    """按 id 从概念库加载；也接受直接传一个 yaml 路径。"""
    path = Path(concept_id)
    if not path.is_file():
        path = Path(cfg.concepts_dir) / f"{concept_id}.yaml"
    if not path.is_file():
        raise ConceptError(
            f"找不到概念 {concept_id!r}，已有：{[c.id for c in list_concepts(cfg)]}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_concept(data, source_path=path)


def list_concepts(cfg: Config = DEFAULT) -> list[Concept]:
    out: list[Concept] = []
    for path in sorted(Path(cfg.concepts_dir).glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        out.append(parse_concept(data, source_path=path))
    return out


def resolve_group_ids(concept: Concept, parts: Iterable[Part]) -> dict[str, int]:
    """给每个部件分配 ControlNet 用的组 ID。

    同一 ``groups`` 条目里的部件共享一个 ID，这样 ctrl 图上它们是一整块，
    canny 就不会在大腿/小腿/脚的接缝处画出横线——重绘后膝盖不会"断开"。
    """
    part_names = [p.name for p in parts]
    group_of: dict[str, int] = {}
    next_id = 1
    for group in concept.groups:
        members = [m for m in group if m in part_names]
        if not members:
            continue
        for m in members:
            group_of[m] = next_id
        next_id += 1
    for name in part_names:
        if name not in group_of:
            group_of[name] = next_id
            next_id += 1
    return group_of
