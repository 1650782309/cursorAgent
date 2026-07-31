"""侦察阶段：识别 Unity 版本、脚本后端、热更方案、第三方栈与资源保护强度。"""

from __future__ import annotations

import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Iterable

from .signatures import SIGNATURES, Signature
from .source import Entry, Source

UNITY_VERSION_RE = re.compile(rb"(\d{4}|[3-6])\.\d+\.\d+[abfpx]\d+")
IL2CPP_METADATA_MAGIC = b"\xaf\x1b\xb1\xfa"
BUNDLE_MAGICS = (b"UnityFS", b"UnityWeb", b"UnityRaw", b"UnityArchive")
ASSET_EXT = (
    ".bundle", ".unity3d", ".assetbundle", ".ab", ".bytes", ".dat", ".res", ".pkg",
)
# 这些扩展名即使躺在 StreamingAssets 里也不是资源容器，别拿去做加密判定
NON_CONTAINER_EXT = (
    ".json", ".txt", ".xml", ".csv", ".manifest", ".hash", ".md", ".ini", ".cfg",
    ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".ogg", ".wav", ".ttf", ".otf",
    ".so", ".dll", ".dylib", ".exe", ".pdb", ".lua", ".js", ".proto",
)
# 单个二进制的字符串扫描上限，避免在超大 GameAssembly 上空耗
STRING_SCAN_BUDGET = 512 << 20


@dataclass
class Detected:
    key: str
    name: str
    category: str
    note: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class BundleProbe:
    path: str
    size: int
    magic: str
    encrypted: bool
    hint: str


@dataclass
class Fingerprint:
    target: str
    source_kind: str
    platform: str = "unknown"
    architectures: list[str] = field(default_factory=list)
    unity_version: str | None = None
    unity_version_evidence: str | None = None
    backend: str = "unknown"
    backend_evidence: list[str] = field(default_factory=list)
    data_dir: str | None = None
    metadata_path: str | None = None
    metadata_encrypted: bool | None = None
    metadata_version: int | None = None
    managed_assemblies: list[str] = field(default_factory=list)
    frameworks: list[Detected] = field(default_factory=list)
    bundles: list[BundleProbe] = field(default_factory=list)
    bundle_encryption: str = "unknown"
    total_files: int = 0
    total_bytes: int = 0
    size_by_ext: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def has(self, key: str) -> bool:
        return any(f.key == key for f in self.frameworks)


def _detect_platform(entries: list[Entry], kind: str) -> tuple[str, list[str]]:
    paths = {e.lower for e in entries}
    archs: list[str] = []
    for e in entries:
        m = re.match(r"lib/([^/]+)/", e.lower)
        if m and m.group(1) not in archs:
            archs.append(m.group(1))
    if kind == "apk" and any(p.startswith("lib/") for p in paths):
        return "android", archs
    if any(p.endswith(".exe") for p in paths) or any("mono-2.0-bdwgc.dll" in p for p in paths):
        return "windows", archs
    if any(p.endswith("gameassembly.dll") for p in paths):
        return "windows", archs
    if any(".app/contents/" in p for p in paths):
        return "macos", archs
    if any(p.endswith("libil2cpp.so") or p.endswith("unityplayer.so") for p in paths):
        return "android/linux", archs
    if any("/frameworks/unityframework" in p for p in paths):
        return "ios", archs
    return "unknown", archs


def _find_data_dir(entries: list[Entry]) -> str | None:
    for e in entries:
        low = e.lower
        for marker in ("assets/bin/data/", "_data/", "/data/"):
            idx = low.find(marker)
            if idx >= 0 and (
                low.endswith("globalgamemanagers")
                or low.endswith("data.unity3d")
                or "/il2cpp_data/" in low
                or "/managed/" in low
            ):
                return e.path[: idx + len(marker)].rstrip("/")
    return None


def _detect_unity_version(src: Source, entries: list[Entry]) -> tuple[str | None, str | None]:
    preferred = ("globalgamemanagers", "data.unity3d", "level0", "mainData")
    ranked: list[Entry] = []
    for want in preferred:
        ranked += [e for e in entries if e.name == want]
    ranked += [e for e in entries if e.name.endswith(".assets")]
    ranked += [e for e in entries if e.name.endswith((".bundle", ".unity3d"))][:20]
    for e in ranked[:60]:
        try:
            head = src.read(e.path, 4096)
        except (OSError, KeyError):
            continue
        m = UNITY_VERSION_RE.search(head)
        if m:
            return m.group(0).decode("ascii", "ignore"), e.path
    return None, None


def _detect_backend(entries: list[Entry]) -> tuple[str, list[str]]:
    ev: list[str] = []
    mono = il2cpp = False
    for e in entries:
        low = e.lower
        name = e.name.lower()
        if name in {"assembly-csharp.dll", "mono-2.0-bdwgc.dll", "libmonobdwgc-2.0.so"} or (
            "/managed/" in low and name == "mscorlib.dll"
        ):
            mono = True
            ev.append(e.path)
        if name in {"gameassembly.dll", "libil2cpp.so"} or "/il2cpp_data/" in low:
            il2cpp = True
            ev.append(e.path)
    if il2cpp and mono:
        return "il2cpp+mono", ev[:6]
    if il2cpp:
        return "il2cpp", ev[:6]
    if mono:
        return "mono", ev[:6]
    return "unknown", ev[:6]


def _probe_metadata(src: Source, entries: list[Entry]) -> tuple[str | None, bool | None, int | None]:
    for e in entries:
        if e.name == "global-metadata.dat":
            try:
                head = src.read(e.path, 8)
            except (OSError, KeyError):
                return e.path, None, None
            if head[:4] == IL2CPP_METADATA_MAGIC:
                ver = struct.unpack_from("<I", head, 4)[0] if len(head) >= 8 else None
                return e.path, False, ver
            return e.path, True, None
    return None, None, None


def _probe_bundles(src: Source, entries: list[Entry], limit: int = 40) -> list[BundleProbe]:
    candidates = [
        e for e in entries
        if e.size > 4096
        and not e.lower.endswith(NON_CONTAINER_EXT)
        and (
            e.lower.endswith(ASSET_EXT)
            or "streamingassets" in e.lower
            or "assetbundles" in e.lower
        )
    ]
    candidates.sort(key=lambda e: -e.size)
    probes: list[BundleProbe] = []
    for e in candidates[:limit]:
        try:
            head = src.read(e.path, 32)
        except (OSError, KeyError):
            continue
        magic = next((m for m in BUNDLE_MAGICS if head.startswith(m)), None)
        if magic:
            probes.append(BundleProbe(e.path, e.size, magic.decode(), False, "标准容器，UnityPy 可直读"))
            continue
        if head[:4] == b"PK\x03\x04":
            probes.append(BundleProbe(e.path, e.size, "zip", False, "zip 容器，先解包再看内层"))
            continue
        if any(m in head for m in BUNDLE_MAGICS):
            off = min(head.find(m) for m in BUNDLE_MAGICS if m in head)
            probes.append(BundleProbe(e.path, e.size, "offset", True, f"头部有 {off} 字节自定义前缀，跳过后可能是标准 bundle"))
            continue
        probes.append(BundleProbe(e.path, e.size, head[:4].hex(), True, "非标准头，需逆 LoadFromMemory 或运行时 dump"))
    return probes


def _scan_strings(src: Source, entries: list[Entry], sigs: Iterable[Signature]) -> dict[str, list[str]]:
    """在关键二进制里搜索特征串。返回 {signature_key: [证据]}。"""
    targets = [
        e for e in entries
        if e.name.lower() in {"gameassembly.dll", "libil2cpp.so", "assembly-csharp.dll", "unityplayer.dll"}
        or (e.lower.endswith(".so") and "lib/" in e.lower)
    ]
    targets.sort(key=lambda e: -e.size)
    patterns = [(s.key, p.encode("utf-8")) for s in sigs for p in s.strings]
    hits: dict[str, list[str]] = {}
    for e in targets[:8]:
        remaining = set(k for k, _ in patterns) - set(hits)
        if not remaining:
            break
        scanned = 0
        tail = b""
        for chunk in src.iter_chunks(e.path):
            buf = tail + chunk
            for key, pat in patterns:
                if key in hits:
                    continue
                if pat in buf:
                    hits.setdefault(key, []).append(f"{e.name}: 字符串 {pat.decode()!r}")
            tail = buf[-64:]
            scanned += len(chunk)
            if scanned >= STRING_SCAN_BUDGET:
                break
    return hits


def _detect_frameworks(src: Source, entries: list[Entry], deep: bool) -> list[Detected]:
    name_blob = [e.lower for e in entries]
    found: dict[str, Detected] = {}
    for sig in SIGNATURES:
        ev = []
        for token in sig.files:
            for low in name_blob:
                if token in low.rsplit("/", 1)[-1] or token in low:
                    ev.append(f"文件 {low}")
                    break
        if ev:
            found[sig.key] = Detected(sig.key, sig.name, sig.category, sig.note, ev[:3])
    if deep:
        pending = [s for s in SIGNATURES if s.key not in found and s.strings]
        for key, ev in _scan_strings(src, entries, pending).items():
            sig = next(s for s in SIGNATURES if s.key == key)
            found[key] = Detected(sig.key, sig.name, sig.category, sig.note, ev[:3])
    return sorted(found.values(), key=lambda d: (d.category, d.name))


def analyze(src: Source, deep: bool = True) -> Fingerprint:
    entries = src.entries()
    fp = Fingerprint(target=str(src.root), source_kind=src.kind)
    fp.total_files = len(entries)
    fp.total_bytes = sum(e.size for e in entries)

    by_ext: dict[str, int] = {}
    for e in entries:
        ext = ("." + e.name.rsplit(".", 1)[-1].lower()) if "." in e.name else "(无扩展名)"
        by_ext[ext] = by_ext.get(ext, 0) + e.size
    fp.size_by_ext = dict(sorted(by_ext.items(), key=lambda kv: -kv[1])[:15])

    fp.platform, fp.architectures = _detect_platform(entries, src.kind)
    fp.data_dir = _find_data_dir(entries)
    fp.unity_version, fp.unity_version_evidence = _detect_unity_version(src, entries)
    fp.backend, fp.backend_evidence = _detect_backend(entries)
    fp.metadata_path, fp.metadata_encrypted, fp.metadata_version = _probe_metadata(src, entries)
    fp.managed_assemblies = sorted(
        e.name for e in entries
        if "/managed/" in e.lower and e.lower.endswith(".dll")
    )[:200]
    fp.frameworks = _detect_frameworks(src, entries, deep)
    fp.bundles = _probe_bundles(src, entries)

    if fp.bundles:
        enc = sum(1 for b in fp.bundles if b.encrypted)
        if enc == 0:
            fp.bundle_encryption = "none"
        elif enc == len(fp.bundles):
            fp.bundle_encryption = "all"
        else:
            fp.bundle_encryption = "partial"

    if fp.unity_version is None:
        fp.warnings.append("未识别到 Unity 版本，可能资源被加密或目标不是 Unity 工程")
    if fp.backend == "unknown":
        fp.warnings.append("未识别到脚本后端，检查是否被加固（Android 看 lib/ 下有没有加固厂商 so）")
    if fp.metadata_encrypted:
        fp.warnings.append("global-metadata.dat 头部 magic 异常，metadata 很可能被加密，走运行时内存 dump")
    if any(f.category == "protect" for f in fp.frameworks):
        fp.warnings.append("检测到加固/反作弊组件，静态流程可能受阻，优先考虑运行时方案")
    return fp
