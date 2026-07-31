"""提取模型与动画：分类 → 导出 → 按人物/物品/场景归档。

产出目录：

  extracted/models/
    人物/<name>/...
    物品/<name>/...
    场景/<name>/...
    特效/ UI/ 其他/
    _index.json          # 完整清单（含分类证据）
    _summary.md
    _raw/                # 外部工具原始输出（未分类）
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import assetscan
from .classify import CATEGORY_DIRS, AssetHint, Classification, classify_asset
from .exporters import discover, run_assetripper, run_assetstudio
from .source import Source

try:
    import UnityPy  # type: ignore

    HAS_UNITYPY = True
except Exception:  # pragma: no cover
    UnityPy = None  # type: ignore
    HAS_UNITYPY = False


SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff\-.]+", re.UNICODE)


@dataclass
class ExtractedItem:
    name: str
    category: str
    label: str
    confidence: str
    source_container: str
    asset_type: str
    clips: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    export_format: str = ""
    score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractReport:
    items: list[ExtractedItem] = field(default_factory=list)
    backend: str = "none"
    exporter_path: str | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "exporter_path": self.exporter_path,
            "counts": self.counts,
            "notes": self.notes,
            "errors": self.errors,
            "items": [i.to_dict() for i in self.items],
        }


def _safe(name: str, fallback: str = "unnamed") -> str:
    s = SAFE_NAME.sub("_", name).strip("._")
    return s[:80] or fallback


def _unique_dir(root: Path, name: str) -> Path:
    base = root / _safe(name)
    if not base.exists():
        base.mkdir(parents=True, exist_ok=True)
        return base
    i = 2
    while True:
        cand = root / f"{_safe(name)}_{i}"
        if not cand.exists():
            cand.mkdir(parents=True, exist_ok=True)
            return cand
        i += 1


def _export_obj_and_textures(
    src: Source,
    hint: AssetHint,
    out_dir: Path,
    unity_version: str | None,
) -> list[str]:
    """UnityPy 降级路径：Mesh → OBJ，贴图 → PNG。动画只能出 JSON 曲线摘要。"""
    if not HAS_UNITYPY:
        return []
    if unity_version:
        UnityPy.config.FALLBACK_UNITY_VERSION = unity_version

    outputs: list[str] = []
    local = src.local_path(hint.container)
    try:
        env = UnityPy.load(str(local)) if local else UnityPy.load(src.read(hint.container))
    except Exception:
        return outputs

    for obj in env.objects:
        if hint.path_id is not None and getattr(obj, "path_id", None) != hint.path_id:
            # 同容器内仍导出相关贴图与匹配名字的 mesh
            pass

        tname = obj.type.name
        try:
            data = obj.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", None) or getattr(data, "name", None) or ""

        if tname == "Mesh" and (not hint.name or name == hint.name or hint.asset_type == "Mesh"):
            if hint.path_id is not None and getattr(obj, "path_id", None) != hint.path_id:
                if name != hint.name:
                    continue
            try:
                text = data.export()
            except Exception:
                continue
            fp = out_dir / f"{_safe(name or hint.name)}.obj"
            fp.write_text(text, encoding="utf-8", newline="\n")
            outputs.append(str(fp))

        elif tname == "Texture2D" and obj.assets_file is not None:
            # 同容器贴图一并导出，方便预览
            try:
                img = data.image
            except Exception:
                continue
            if img is None:
                continue
            fp = out_dir / "textures" / f"{_safe(str(name) or 'tex')}.png"
            fp.parent.mkdir(parents=True, exist_ok=True)
            img.save(fp)
            outputs.append(str(fp))

        elif tname == "AnimationClip" and name in set(hint.clip_names):
            # 曲线摘要，不是可播放格式
            summary = {
                "name": name,
                "legacy": bool(getattr(data, "m_Legacy", False)),
                "sample_rate": getattr(data, "m_SampleRate", None),
                "note": "JSON 摘要不可直接播放；可播放 FBX 需 AssetStudio",
            }
            # 尽量抓取 clip 长度
            for attr in ("m_MuscleClip", "duration", "m_Duration"):
                v = getattr(data, attr, None)
                if v is not None and not callable(v):
                    try:
                        summary["duration_hint"] = float(v)
                    except Exception:
                        summary["duration_hint"] = str(v)[:80]
                    break
            fp = out_dir / "animations" / f"{_safe(str(name))}.json"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            outputs.append(str(fp))

    return outputs


def _match_exports_to_item(name: str, export_root: Path) -> list[Path]:
    """在外部工具的扁平输出里，按文件名模糊匹配属于该模型的文件。"""
    if not export_root.exists():
        return []
    needle = _safe(name).lower()
    raw = name.lower()
    hits: list[Path] = []
    for p in export_root.rglob("*"):
        if not p.is_file():
            continue
        stem = p.stem.lower()
        if stem == raw or stem == needle or stem.startswith(needle) or needle.startswith(stem):
            if p.suffix.lower() in {".fbx", ".obj", ".png", ".tga", ".jpg", ".anim", ".json", ".yaml"}:
                hits.append(p)
    return hits


def _write_summary(report: ExtractReport, out: Path) -> None:
    lines = [
        "# 模型 / 动画提取摘要",
        "",
        f"- 导出后端：`{report.backend}`"
        + (f" (`{report.exporter_path}`)" if report.exporter_path else ""),
        f"- 共 {len(report.items)} 项",
        "",
        "## 分类统计",
        "",
        "| 类别 | 数量 |",
        "| --- | --- |",
    ]
    for key, label in CATEGORY_DIRS.items():
        lines.append(f"| {label} ({key}) | {report.counts.get(key, 0)} |")
    lines += ["", "## 明细", ""]
    for it in report.items:
        lines.append(
            f"- **{it.label}/{it.name}** · {it.asset_type} · 置信度 {it.confidence}"
            f" · clips={len(it.clips)} · 输出 {len(it.outputs)} 个文件"
        )
    if report.notes:
        lines += ["", "## 说明", ""]
        for n in report.notes:
            lines.append(f"- {n}")
    if report.errors:
        lines += ["", "## 错误", ""]
        for e in report.errors:
            lines.append(f"- {e}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract(
    src: Source,
    out_dir: Path,
    *,
    unity_version: str | None = None,
    format: str = "fbx",          # fbx | obj | classify-only
    max_containers: int = 400,
    prefer: str = "auto",         # auto | assetstudio | assetripper | obj
    vendor_dir: Path | None = None,
) -> ExtractReport:
    out_dir = Path(out_dir)
    models_root = out_dir / "models"
    models_root.mkdir(parents=True, exist_ok=True)
    for label in CATEGORY_DIRS.values():
        (models_root / label).mkdir(exist_ok=True)

    report = ExtractReport()
    scan = assetscan.scan(src, unity_version=unity_version, max_containers=max_containers)
    report.errors.extend(scan.errors)

    # 分类对象：模型为主；孤立特效/UI 也进清单
    targets: list[AssetHint] = list(scan.models)
    targets.extend(h for h in scan.others if h.asset_type in {
        "ParticleSystem", "TrailRenderer", "Sprite", "SpriteAtlas",
    })

    classified: list[tuple[AssetHint, Classification]] = [
        (h, classify_asset(h)) for h in targets
    ]

    exporter = discover(vendor_dir)
    report.notes.extend(exporter.notes)

    want_fbx = format == "fbx" and prefer != "obj"
    raw_dir = models_root / "_raw"
    used_backend = "classify-only" if format == "classify-only" else "obj"

    if want_fbx and prefer in {"auto", "assetstudio", "assetripper"}:
        kind = exporter.kind if prefer == "auto" else prefer
        if kind == "assetstudio" and exporter.available and exporter.kind == "assetstudio":
            report.notes.append("使用 AssetStudio 导出可播放 FBX")
            proc = run_assetstudio(exporter.path, Path(src.root), raw_dir)
            if proc.returncode == 0:
                used_backend = "assetstudio"
                report.exporter_path = str(exporter.path)
            else:
                report.errors.append(
                    f"AssetStudio 失败 (code={proc.returncode}): "
                    f"{(proc.stderr or proc.stdout or '')[:300]}"
                )
                report.notes.append("AssetStudio 失败，降级为 OBJ + 动画 JSON")
        elif kind == "assetripper" and (
            (exporter.available and exporter.kind == "assetripper")
            or (prefer == "assetripper" and exporter.available)
        ):
            # 若 prefer=assetripper 但发现的是 assetstudio，再搜一次？简化：仅当 discover 到 ripper
            if exporter.kind == "assetripper" and exporter.available:
                report.notes.append(
                    "使用 AssetRipper 导出 Unity 工程（可播放 FBX 需在 Unity 中二次导出，"
                    "或改用 AssetStudio）"
                )
                proc = run_assetripper(exporter.path, Path(src.root), raw_dir / "ripper_project")
                if proc.returncode == 0:
                    used_backend = "assetripper"
                    report.exporter_path = str(exporter.path)
                else:
                    report.errors.append(
                        f"AssetRipper 失败 (code={proc.returncode}): "
                        f"{(proc.stderr or proc.stdout or '')[:300]}"
                    )
            else:
                report.notes.append("未找到 AssetRipper，降级为 OBJ + 动画 JSON")
        elif want_fbx:
            report.notes.append(
                "未找到可播放 FBX 导出器。已按分类导出 OBJ/贴图/动画摘要；"
                "安装 AssetStudio 后设置 URECON_ASSETSTUDIO 再跑一次即可得到 FBX。"
            )

    if format == "classify-only":
        used_backend = "classify-only"

    report.backend = used_backend

    for hint, clf in classified:
        label_dir = models_root / clf.label
        item_dir = _unique_dir(label_dir, hint.name or hint.asset_type)
        meta = {
            "name": hint.name,
            "category": clf.category,
            "label": clf.label,
            "confidence": clf.confidence,
            "score": clf.score,
            "scores": clf.scores,
            "evidence": clf.evidence,
            "source_container": hint.container,
            "asset_type": hint.asset_type,
            "bone_count": hint.bone_count,
            "vertex_count": hint.vertex_count,
            "clips": hint.clip_names,
        }
        (item_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        outputs: list[str] = [str(item_dir / "meta.json")]
        export_format = "meta-only"

        if format != "classify-only":
            if used_backend == "assetstudio":
                matched = _match_exports_to_item(hint.name, raw_dir)
                for src_file in matched:
                    dest = item_dir / src_file.name
                    if src_file.suffix.lower() in {".png", ".tga", ".jpg", ".jpeg"}:
                        dest = item_dir / "textures" / src_file.name
                        dest.parent.mkdir(exist_ok=True)
                    shutil.copy2(src_file, dest)
                    outputs.append(str(dest))
                if any(Path(p).suffix.lower() == ".fbx" for p in outputs):
                    export_format = "fbx"
                else:
                    # 没匹配到 FBX 时补 OBJ 降级
                    extra = _export_obj_and_textures(src, hint, item_dir, unity_version)
                    outputs.extend(extra)
                    export_format = "obj+json" if extra else "meta-only"
                    if not matched:
                        report.notes.append(
                            f"{hint.name}: AssetStudio 输出中未匹配到同名 FBX，已写 OBJ 降级"
                        )
            elif used_backend == "assetripper":
                # 在 ripper 工程里记一个指针，方便人工二次导出
                pointer = {
                    "ripper_project": str(raw_dir / "ripper_project"),
                    "hint_name": hint.name,
                    "next_step": "用 Unity 打开工程，选中该模型，FBX Exporter 导出到本目录",
                }
                ptr = item_dir / "ripper_pointer.json"
                ptr.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
                outputs.append(str(ptr))
                extra = _export_obj_and_textures(src, hint, item_dir, unity_version)
                outputs.extend(extra)
                export_format = "ripper+obj"
            else:
                extra = _export_obj_and_textures(src, hint, item_dir, unity_version)
                outputs.extend(extra)
                export_format = "obj+json" if extra else "meta-only"

        item = ExtractedItem(
            name=hint.name,
            category=clf.category,
            label=clf.label,
            confidence=clf.confidence,
            source_container=hint.container,
            asset_type=hint.asset_type,
            clips=list(hint.clip_names),
            outputs=outputs,
            evidence=list(clf.evidence),
            export_format=export_format,
            score=clf.score,
        )
        report.items.append(item)
        report.counts[clf.category] = report.counts.get(clf.category, 0) + 1

    # 未关联到模型的 clip 单独归档
    linked = {c for clips in (scan.clip_links or {}).values() for c in clips}
    for clip in scan.clips:
        if clip.name in linked:
            continue
        clf = classify_asset(clip)
        label_dir = models_root / clf.label / "_orphan_clips"
        label_dir.mkdir(parents=True, exist_ok=True)
        fp = label_dir / f"{_safe(clip.name)}.json"
        fp.write_text(
            json.dumps({
                "name": clip.name,
                "container": clip.container,
                "category": clf.category,
                "evidence": clf.evidence,
                "note": "未关联到具体模型的孤立动画",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    index_path = models_root / "_index.json"
    index_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_summary(report, models_root / "_summary.md")
    report.notes.append(f"清单: {index_path}")
    return report
