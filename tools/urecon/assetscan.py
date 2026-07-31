"""从 Unity 资源容器里扫描模型 / 动画相关对象，产出分类用的 AssetHint。"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field

from .classify import AssetHint, link_clips_to_models
from .fingerprint import ASSET_EXT, NON_CONTAINER_EXT
from .source import Entry, Source

try:
    import UnityPy  # type: ignore

    HAS_UNITYPY = True
except Exception:  # pragma: no cover
    UnityPy = None  # type: ignore
    HAS_UNITYPY = False


MESH_TYPES = {"Mesh", "SkinnedMeshRenderer", "MeshRenderer", "MeshFilter"}
ANIM_TYPES = {"AnimationClip", "Animator", "AnimatorController", "Avatar"}
TEX_TYPES = {"Texture2D", "Sprite"}


@dataclass
class ScanResult:
    models: list[AssetHint] = field(default_factory=list)
    clips: list[AssetHint] = field(default_factory=list)
    textures: list[AssetHint] = field(default_factory=list)
    others: list[AssetHint] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    containers_scanned: int = 0
    clip_links: dict[str, list[str]] = field(default_factory=dict)

    @property
    def all_hints(self) -> list[AssetHint]:
        return [*self.models, *self.clips, *self.textures, *self.others]


def _candidates(entries: list[Entry], limit: int) -> list[Entry]:
    out = []
    for e in entries:
        low = e.lower
        if e.size < 64 or low.endswith(NON_CONTAINER_EXT):
            continue
        if (
            low.endswith(ASSET_EXT)
            or low.endswith((".assets", ".unity3d", ".resource", ".resS"))
            or "streamingassets" in low
            or "assetbundles" in low
            or e.name in {"data.unity3d", "globalgamemanagers", "resources.assets"}
            or e.name.startswith(("level", "sharedassets"))
        ):
            out.append(e)
    out.sort(key=lambda e: -e.size)
    return out[:limit]


def _safe_name(obj, data=None) -> str:
    if data is not None:
        n = getattr(data, "m_Name", None) or getattr(data, "name", None)
        if n:
            return str(n)
    try:
        return str(obj.peek_name() or "")
    except Exception:
        return ""


def _read(obj):
    try:
        return obj.read()
    except Exception:
        return None


def scan(
    src: Source,
    *,
    unity_version: str | None = None,
    max_containers: int = 400,
) -> ScanResult:
    if not HAS_UNITYPY:
        raise RuntimeError(
            "提取模型需要 UnityPy。安装: pip install 'urecon[assets]' 或 pip install UnityPy"
        )

    if unity_version:
        UnityPy.config.FALLBACK_UNITY_VERSION = unity_version

    result = ScanResult()
    entries = _candidates(src.entries(), max_containers)

    for e in entries:
        result.containers_scanned += 1
        local = src.local_path(e.path)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                env = UnityPy.load(str(local)) if local else UnityPy.load(src.read(e.path))
        except Exception as exc:
            result.errors.append(f"{e.path}: {type(exc).__name__}: {exc}"[:200])
            continue

        # 先收集本容器内的 Animator / Avatar / Clip，方便挂到模型上
        local_clips: list[str] = []
        has_animator = False
        has_avatar = False
        is_humanoid = False

        for obj in env.objects:
            tname = obj.type.name
            if tname == "AnimationClip":
                data = _read(obj)
                name = _safe_name(obj, data)
                if name:
                    local_clips.append(name)
                    result.clips.append(AssetHint(
                        name=name, container=e.path, asset_type=tname,
                        path_id=getattr(obj, "path_id", None),
                    ))
            elif tname == "Animator":
                has_animator = True
            elif tname == "Avatar":
                has_avatar = True
                data = _read(obj)
                # m_IsHuman 在部分版本存在
                if data is not None and bool(getattr(data, "m_IsHuman", False)):
                    is_humanoid = True

        for obj in env.objects:
            tname = obj.type.name
            data = _read(obj)
            name = _safe_name(obj, data)

            if tname == "Mesh":
                verts = int(getattr(data, "m_VertexCount", 0) or 0) if data else 0
                bone_influence = 0
                if data is not None:
                    bw = getattr(data, "m_BoneWeights", None) or getattr(data, "m_Skin", None)
                    if bw:
                        bone_influence = len(bw)
                hint = AssetHint(
                    name=name or f"Mesh_{getattr(obj, 'path_id', 0)}",
                    container=e.path,
                    asset_type="Mesh",
                    path_id=getattr(obj, "path_id", None),
                    vertex_count=verts,
                    bone_count=bone_influence,
                    has_skin=bone_influence > 0,
                    has_avatar=has_avatar,
                    has_animator=has_animator,
                    is_humanoid=is_humanoid,
                    clip_names=list(local_clips),
                )
                result.models.append(hint)

            elif tname == "SkinnedMeshRenderer":
                bone_count = 0
                mesh_name = ""
                if data is not None:
                    bones = getattr(data, "m_Bones", None) or []
                    bone_count = len(bones)
                    try:
                        mesh_ptr = getattr(data, "m_Mesh", None)
                        if mesh_ptr:
                            mesh_name = _safe_name(mesh_ptr, mesh_ptr.read())
                    except Exception:
                        pass
                hint = AssetHint(
                    name=name or mesh_name or f"Skin_{getattr(obj, 'path_id', 0)}",
                    container=e.path,
                    asset_type="SkinnedMeshRenderer",
                    path_id=getattr(obj, "path_id", None),
                    bone_count=bone_count,
                    has_skin=True,
                    has_avatar=has_avatar,
                    has_animator=has_animator,
                    is_humanoid=is_humanoid,
                    clip_names=list(local_clips),
                    bound_mesh_names=[mesh_name] if mesh_name else [],
                )
                result.models.append(hint)

            elif tname in TEX_TYPES:
                result.textures.append(AssetHint(
                    name=name or f"Tex_{getattr(obj, 'path_id', 0)}",
                    container=e.path,
                    asset_type=tname,
                    path_id=getattr(obj, "path_id", None),
                ))

            elif tname in {"ParticleSystem", "TrailRenderer", "Sprite", "SpriteAtlas"}:
                result.others.append(AssetHint(
                    name=name or tname,
                    container=e.path,
                    asset_type=tname,
                    path_id=getattr(obj, "path_id", None),
                ))

    result.clip_links = link_clips_to_models(result.models, result.clips)
    for m in result.models:
        linked = result.clip_links.get(m.name) or []
        # 合并去重，保持原有同容器 clips
        merged = list(dict.fromkeys([*m.clip_names, *linked]))
        m.clip_names = merged
    return result
