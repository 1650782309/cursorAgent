"""资源清点：容器列表 + 对象级明细 + 类型/体积分布。

UnityPy 可用时做对象级解析，不可用时降级为文件级统计，不会直接失败。
"""

from __future__ import annotations

import contextlib
import csv
import io
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .fingerprint import ASSET_EXT, BUNDLE_MAGICS, NON_CONTAINER_EXT
from .source import Entry, Source

try:  # 可选依赖
    import UnityPy  # type: ignore

    HAS_UNITYPY = True
except Exception:  # pragma: no cover - 取决于环境
    UnityPy = None  # type: ignore
    HAS_UNITYPY = False


@dataclass
class ObjectRow:
    container: str
    type: str
    name: str
    size: int
    detail: str = ""


@dataclass
class ContainerRow:
    path: str
    size: int
    magic: str
    objects: int
    parsed: bool
    error: str = ""


@dataclass
class Inventory:
    containers: list[ContainerRow] = field(default_factory=list)
    objects: list[ObjectRow] = field(default_factory=list)
    type_count: dict[str, int] = field(default_factory=dict)
    type_bytes: dict[str, int] = field(default_factory=dict)
    texture_formats: dict[str, int] = field(default_factory=dict)
    audio_formats: dict[str, int] = field(default_factory=dict)
    unparsed: int = 0
    engine: str = "file-only"

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "containers": len(self.containers),
            "objects": len(self.objects),
            "unparsed_containers": self.unparsed,
            "type_count": self.type_count,
            "type_bytes": self.type_bytes,
            "texture_formats": self.texture_formats,
            "audio_formats": self.audio_formats,
        }


def _candidates(entries: list[Entry]) -> list[Entry]:
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
            or e.name.startswith("level")
            or e.name.startswith("sharedassets")
        ):
            out.append(e)
    return sorted(out, key=lambda e: -e.size)


def _magic_of(src: Source, e: Entry) -> str:
    try:
        head = src.read(e.path, 16)
    except (OSError, KeyError):
        return "?"
    for m in BUNDLE_MAGICS:
        if head.startswith(m):
            return m.decode()
    if head[:8] in (b"UnityRaw",):
        return "UnityRaw"
    return head[:4].hex()


def _object_detail(obj) -> tuple[str, str, str]:
    """返回 (name, detail, kind_extra)。任何解析异常都退回空值。"""
    try:
        data = obj.read()
    except Exception:
        return "", "", ""
    name = getattr(data, "m_Name", "") or getattr(data, "name", "") or ""
    tname = obj.type.name
    if tname == "Texture2D":
        fmt = getattr(data, "m_TextureFormat", None)
        w = getattr(data, "m_Width", "?")
        h = getattr(data, "m_Height", "?")
        fmt_name = getattr(fmt, "name", str(fmt))
        return str(name), f"{w}x{h} {fmt_name}", f"tex:{fmt_name}"
    if tname == "AudioClip":
        fmt = getattr(data, "m_CompressionFormat", None)
        load = getattr(data, "m_LoadType", None)
        fmt_name = getattr(fmt, "name", str(fmt))
        return str(name), f"{fmt_name} load={getattr(load, 'name', load)}", f"audio:{fmt_name}"
    if tname == "Mesh":
        return str(name), f"verts={getattr(data, 'm_VertexCount', '?')}", ""
    if tname == "MonoBehaviour":
        script = getattr(data, "m_Script", None)
        try:
            cls = script.read().m_ClassName if script else ""
        except Exception:
            cls = ""
        return str(name), f"script={cls}", ""
    return str(name), "", ""


def scan(
    src: Source,
    max_containers: int = 400,
    max_objects: int = 200_000,
    unity_version: str | None = None,
) -> Inventory:
    inv = Inventory(engine="UnityPy" if HAS_UNITYPY else "file-only")
    if HAS_UNITYPY and unity_version:
        # 剥离了版本号的 bundle 需要 fallback，否则 UnityPy 直接拒绝解析
        UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    entries = _candidates(src.entries())[:max_containers]
    tcount: Counter[str] = Counter()
    tbytes: defaultdict[str, int] = defaultdict(int)
    tex: Counter[str] = Counter()
    aud: Counter[str] = Counter()

    for e in entries:
        magic = _magic_of(src, e)
        row = ContainerRow(e.path, e.size, magic, 0, False)
        if not HAS_UNITYPY:
            inv.containers.append(row)
            continue
        local = src.local_path(e.path)
        try:
            # UnityPy 解析失败时会往 stdout 打印，这里我们自己记录错误，屏蔽它的噪声
            with contextlib.redirect_stdout(io.StringIO()):
                env = UnityPy.load(str(local)) if local else UnityPy.load(src.read(e.path))
            for obj in env.objects:
                if len(inv.objects) >= max_objects:
                    break
                tname = obj.type.name
                size = int(getattr(obj, "byte_size", 0) or 0)
                name, detail, extra = _object_detail(obj)
                inv.objects.append(ObjectRow(e.path, tname, name, size, detail))
                tcount[tname] += 1
                tbytes[tname] += size
                if extra.startswith("tex:"):
                    tex[extra[4:]] += 1
                elif extra.startswith("audio:"):
                    aud[extra[6:]] += 1
                row.objects += 1
            row.parsed = True
        except Exception as exc:  # 加密/非标准容器
            row.error = f"{type(exc).__name__}: {exc}"[:160]
            inv.unparsed += 1
        inv.containers.append(row)

    inv.type_count = dict(tcount.most_common())
    inv.type_bytes = dict(sorted(tbytes.items(), key=lambda kv: -kv[1]))
    inv.texture_formats = dict(tex.most_common())
    inv.audio_formats = dict(aud.most_common())
    return inv


def write_csv(inv: Inventory, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    written = []

    p = outdir / "containers.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "size", "magic", "objects", "parsed", "error"])
        for c in inv.containers:
            w.writerow([c.path, c.size, c.magic, c.objects, int(c.parsed), c.error])
    written.append(p)

    if inv.objects:
        p = outdir / "inventory.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["container", "type", "name", "size", "detail"])
            for o in inv.objects:
                w.writerow([o.container, o.type, o.name, o.size, o.detail])
        written.append(p)
    return written
