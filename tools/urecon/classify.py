"""模型 / 动画自动分类。

分类不是精确科学，而是一组可解释的启发式打分。结果带 evidence，方便人工复核。
默认类别（输出目录名用中文）：

  character → 人物
  item      → 物品
  scene     → 场景
  fx        → 特效
  ui        → UI
  other     → 其他
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable

CATEGORY_DIRS = {
    "character": "人物",
    "item": "物品",
    "scene": "场景",
    "fx": "特效",
    "ui": "UI",
    "other": "其他",
}

# (category, weight, patterns) —— 命中路径/名字时加分
KEYWORD_RULES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("character", 6, (
        "character", "characters", "char", "chars", "hero", "heroes", "npc",
        "avatar", "player", "monster", "enemy", "boss", "role", "actor",
        "creature", "pet", "companion", "humanoid", "spine", "live2d",
        "角色", "人物", "主角", "敌人", "怪物", "npc",
    )),
    ("item", 6, (
        "item", "items", "prop", "props", "weapon", "weapons", "equip",
        "equipment", "gear", "drop", "loot", "pickup", "collectable",
        "artifact", "tool", "gadget", "furniture",
        "物品", "道具", "武器", "装备", "掉落",
    )),
    ("scene", 6, (
        "scene", "scenes", "map", "maps", "level", "levels", "env",
        "environment", "terrain", "building", "buildings", "room", "rooms",
        "bg", "background", "landscape", "world", "stage", "dungeon",
        "场景", "地图", "关卡", "环境", "地形", "建筑",
    )),
    ("fx", 5, (
        "fx", "vfx", "effect", "effects", "particle", "particles",
        "trail", "slash", "hitfx", "特效", "粒子",
    )),
    ("ui", 5, (
        "ui", "hud", "gui", "icon", "icons", "atlas", "font", "fonts",
        "ugui", "fairygui", "界面", "图标",
    )),
)

LOCOMOTION = re.compile(
    r"(idle|walk|run|jump|attack|skill|die|death|hit|hurt|dance|emote|"
    r"待机|走路|跑步|攻击|技能|死亡)",
    re.I,
)


@dataclass
class AssetHint:
    """分类器用的轻量描述，不依赖 UnityPy 对象本身。"""

    name: str
    container: str = ""
    asset_type: str = ""          # Mesh / SkinnedMeshRenderer / AnimationClip / ...
    path_id: int | None = None
    vertex_count: int = 0
    bone_count: int = 0
    has_skin: bool = False
    has_avatar: bool = False
    has_animator: bool = False
    is_humanoid: bool = False
    clip_names: list[str] = field(default_factory=list)
    texture_names: list[str] = field(default_factory=list)
    bound_mesh_names: list[str] = field(default_factory=list)
    extra_path: str = ""          # Addressables 地址、资源内部 path 等

    @property
    def haystack(self) -> str:
        parts = [self.name, self.container, self.extra_path, *self.bound_mesh_names, *self.clip_names]
        return "/".join(p for p in parts if p).lower().replace("\\", "/")


@dataclass
class Classification:
    category: str
    label: str
    score: float
    scores: dict[str, float]
    evidence: list[str] = field(default_factory=list)
    confidence: str = "low"       # high / medium / low

    def to_dict(self) -> dict:
        return asdict(self)


def _keyword_scores(text: str) -> tuple[dict[str, float], list[str]]:
    scores = {k: 0.0 for k in CATEGORY_DIRS}
    evidence: list[str] = []
    # 按路径段与整串分别匹配，避免短 token 误伤
    tokens = set(re.split(r"[/\\_\-.]+", text))
    tokens.add(text)
    for cat, weight, patterns in KEYWORD_RULES:
        for pat in patterns:
            pl = pat.lower()
            if pl in tokens or f"/{pl}/" in f"/{text}/" or text.endswith(f"/{pl}"):
                scores[cat] += weight
                evidence.append(f"关键词 '{pat}' → {CATEGORY_DIRS[cat]} +{weight}")
                break  # 同一类别只计一次关键词命中，避免刷分
    return scores, evidence


def classify_asset(hint: AssetHint) -> Classification:
    scores = {k: 0.0 for k in CATEGORY_DIRS}
    evidence: list[str] = []

    kw_scores, kw_ev = _keyword_scores(hint.haystack)
    for k, v in kw_scores.items():
        scores[k] += v
    evidence.extend(kw_ev)

    # —— 结构信号 ——
    if hint.has_skin or hint.asset_type in {"SkinnedMeshRenderer", "SkinnedMesh"}:
        scores["character"] += 3
        evidence.append("含蒙皮网格 → 人物 +3")
    if hint.bone_count >= 30:
        scores["character"] += 3
        evidence.append(f"骨骼数 {hint.bone_count} ≥ 30 → 人物 +3")
    elif hint.bone_count >= 10:
        scores["character"] += 2
        evidence.append(f"骨骼数 {hint.bone_count} ≥ 10 → 人物 +2")
    if hint.is_humanoid or hint.has_avatar:
        scores["character"] += 4
        evidence.append("Humanoid/Avatar → 人物 +4")
    if hint.has_animator:
        scores["character"] += 1
        evidence.append("挂有 Animator → 人物 +1")

    loco = [c for c in hint.clip_names if LOCOMOTION.search(c)]
    if loco:
        scores["character"] += 3
        evidence.append(f"含位移类动画 {loco[:3]} → 人物 +3")

    if hint.asset_type == "AnimationClip" and not hint.has_skin:
        # 孤立 clip：按名字分；分不出来进其他
        if not any(scores[c] > 0 for c in ("character", "item", "scene", "fx", "ui")):
            scores["other"] += 1

    if hint.vertex_count >= 20_000 and not hint.has_skin:
        scores["scene"] += 2
        evidence.append(f"高模无蒙皮 verts={hint.vertex_count} → 场景 +2")
    elif 0 < hint.vertex_count <= 500 and not hint.has_skin and not hint.has_animator:
        scores["item"] += 1
        evidence.append(f"低模无蒙皮 verts={hint.vertex_count} → 物品 +1")

    if hint.asset_type in {"ParticleSystem", "TrailRenderer"}:
        scores["fx"] += 4
        evidence.append(f"{hint.asset_type} → 特效 +4")
    if hint.asset_type in {"Sprite", "SpriteAtlas", "Canvas", "RectTransform"}:
        scores["ui"] += 4
        evidence.append(f"{hint.asset_type} → UI +4")

    # 容器名里的 ui_*.bundle 之类
    cname = hint.container.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if cname.startswith("ui") or "/ui/" in hint.haystack:
        scores["ui"] += 2
        evidence.append("容器/路径像 UI → UI +2")

    best = max(scores, key=scores.get)
    best_score = scores[best]
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    if best_score <= 0:
        best, best_score = "other", 0.0
        evidence.append("无有效信号，归入其他")

    gap = best_score - second
    if best_score >= 8 and gap >= 3:
        confidence = "high"
    elif best_score >= 4 and gap >= 1:
        confidence = "medium"
    else:
        confidence = "low"

    return Classification(
        category=best,
        label=CATEGORY_DIRS[best],
        score=best_score,
        scores=scores,
        evidence=evidence,
        confidence=confidence,
    )


def classify_many(hints: Iterable[AssetHint]) -> list[tuple[AssetHint, Classification]]:
    return [(h, classify_asset(h)) for h in hints]


def common_prefix(names: list[str], min_len: int = 3) -> str | None:
    if not names:
        return None
    cleaned = [re.sub(r"[\d_\-]+$", "", n) for n in names if n]
    if not cleaned:
        return None
    prefix = cleaned[0]
    for n in cleaned[1:]:
        while prefix and not n.startswith(prefix):
            prefix = prefix[:-1]
        if len(prefix) < min_len:
            return None
    prefix = prefix.rstrip("_-")
    return prefix if len(prefix) >= min_len else None


def link_clips_to_models(
    models: list[AssetHint],
    clips: list[AssetHint],
) -> dict[str, list[str]]:
    """把 AnimationClip 名字挂到最像的模型上。返回 {model.name: [clip.name, ...]}。"""
    result: dict[str, list[str]] = {m.name: list(m.clip_names) for m in models}
    claimed: set[str] = set()

    # 1) 同容器优先
    by_container: dict[str, list[AssetHint]] = {}
    for m in models:
        by_container.setdefault(m.container, []).append(m)

    for clip in clips:
        if clip.name in claimed:
            continue
        candidates = by_container.get(clip.container, models)
        best: AssetHint | None = None
        best_score = 0
        cl = clip.name.lower()
        for m in candidates:
            ml = m.name.lower()
            score = 0
            if ml and (cl.startswith(ml) or ml.startswith(cl)):
                score += 5
            pref = common_prefix([m.name, clip.name], min_len=3)
            if pref:
                score += len(pref)
            if m.container == clip.container:
                score += 2
            if score > best_score:
                best_score, best = score, m
        if best and best_score >= 3:
            result.setdefault(best.name, []).append(clip.name)
            claimed.add(clip.name)

    return result
