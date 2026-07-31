"""把指纹、清点、计划渲染成结构化 Markdown 报告。"""

from __future__ import annotations

from datetime import datetime

from .fingerprint import Fingerprint
from .inventory import Inventory
from .plan import Step
from .signatures import CATEGORY_LABEL


def human(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} B"
        v /= 1024
    return f"{v:.1f} GB"


def _yesno(v: bool | None) -> str:
    return {True: "是", False: "否", None: "未知"}[v]


def render(fp: Fingerprint, inv: Inventory | None, steps: list[Step], title: str | None = None) -> str:
    L: list[str] = []
    name = title or fp.target.rstrip("/").rsplit("/", 1)[-1]
    L.append(f"# {name} 逆向学习报告")
    L.append("")
    L.append(f"> 由 `urecon` 于 {datetime.now():%Y-%m-%d %H:%M} 生成。第 5、6 节需要手写。")
    L.append("")

    L.append("## 1. 基础指纹")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    L.append(f"| 目标 | `{fp.target}` |")
    L.append(f"| 平台 | {fp.platform}{' / ' + ', '.join(fp.architectures) if fp.architectures else ''} |")
    L.append(f"| Unity 版本 | {fp.unity_version or '未识别'} |")
    L.append(f"| 脚本后端 | {fp.backend} |")
    if fp.metadata_path:
        L.append(f"| metadata | `{fp.metadata_path}`（加密: {_yesno(fp.metadata_encrypted)}"
                 + (f"，版本 {fp.metadata_version}" if fp.metadata_version else "") + "） |")
    L.append(f"| 文件数 / 体积 | {fp.total_files} / {human(fp.total_bytes)} |")
    L.append(f"| bundle 加密 | {fp.bundle_encryption} |")
    L.append("")

    if fp.size_by_ext:
        L.append("体积前几的扩展名：")
        L.append("")
        L.append("| 扩展名 | 体积 | 占比 |")
        L.append("| --- | --- | --- |")
        for ext, size in list(fp.size_by_ext.items())[:10]:
            pct = size / fp.total_bytes * 100 if fp.total_bytes else 0
            L.append(f"| `{ext}` | {human(size)} | {pct:.1f}% |")
        L.append("")

    if fp.warnings:
        L.append("需要注意：")
        L.append("")
        for w in fp.warnings:
            L.append(f"- {w}")
        L.append("")

    L.append("## 2. 技术栈清单")
    L.append("")
    if not fp.frameworks:
        L.append("未识别到已知框架。要么是高度自研，要么被混淆了名字——后者可以从 `dump.cs` 的类名风格再判断一次。")
    else:
        by_cat: dict[str, list] = {}
        for f in fp.frameworks:
            by_cat.setdefault(f.category, []).append(f)
        for cat, items in by_cat.items():
            L.append(f"**{CATEGORY_LABEL.get(cat, cat)}**")
            L.append("")
            for it in items:
                ev = it.evidence[0] if it.evidence else ""
                L.append(f"- **{it.name}** — {ev}")
                if it.note:
                    L.append(f"  - {it.note}")
            L.append("")
    if fp.managed_assemblies:
        L.append(f"<details><summary>托管程序集 {len(fp.managed_assemblies)} 个</summary>")
        L.append("")
        L.append("```")
        L.extend(fp.managed_assemblies)
        L.append("```")
        L.append("")
        L.append("</details>")
        L.append("")

    L.append("## 3. 资源管线")
    L.append("")
    if inv is None:
        L.append("未执行资源清点。运行 `urecon inventory <target>` 后重新生成报告。")
        L.append("")
    else:
        L.append(f"解析引擎：{inv.engine}；容器 {len(inv.containers)} 个，"
                 f"解析失败 {inv.unparsed} 个，对象 {len(inv.objects)} 个。")
        L.append("")
        if inv.type_bytes:
            total = sum(inv.type_bytes.values()) or 1
            L.append("| 资源类型 | 数量 | 体积 | 占比 |")
            L.append("| --- | --- | --- | --- |")
            for t, b in list(inv.type_bytes.items())[:15]:
                L.append(f"| {t} | {inv.type_count.get(t, 0)} | {human(b)} | {b / total * 100:.1f}% |")
            L.append("")
        if inv.texture_formats:
            L.append("贴图格式分布：" + "、".join(f"{k} × {v}" for k, v in list(inv.texture_formats.items())[:10]))
            L.append("")
            L.append("> 从格式分档能反推机型覆盖策略：ASTC 多档说明按设备分级打包，单一 ETC2 说明走保守兼容路线。")
            L.append("")
        if inv.audio_formats:
            L.append("音频格式分布：" + "、".join(f"{k} × {v}" for k, v in list(inv.audio_formats.items())[:10]))
            L.append("")
        big = sorted(inv.containers, key=lambda c: -c.size)[:10]
        if big:
            L.append("最大的容器：")
            L.append("")
            L.append("| 容器 | 体积 | magic | 对象数 |")
            L.append("| --- | --- | --- | --- |")
            for c in big:
                L.append(f"| `{c.path}` | {human(c.size)} | {c.magic} | {c.objects if c.parsed else '解析失败'} |")
            L.append("")
        L.append("待回答：分包粒度按什么维度？共享资源抽了公共包还是冗余？首包与热更的边界在哪？")
        L.append("")

    L.append("## 4. 代码架构")
    L.append("")
    L.append("_手写。建议画一张分层图，标出：入口流程、全局 Manager、逻辑层跑在哪（AOT/热更 DLL/Lua）、数据流向。_")
    L.append("")
    L.append("从 `dump.cs` 起步的检索：")
    L.append("")
    L.append("```bash")
    L.append("rg -n 'class .*Manager' decompiled/dump.cs | head -50")
    L.append("rg -n 'class .*(Battle|Skill|Buff)' decompiled/dump.cs")
    L.append("rg -n 'class .*(Net|Socket|Protocol|Msg)' decompiled/dump.cs")
    L.append("rg -n '\\[Serializable\\]' -A5 decompiled/dump.cs")
    L.append("```")
    L.append("")

    L.append("## 5. 三个「我没想到」")
    L.append("")
    L.append("_手写，必填。写让你意外的设计决策：为什么意外，他们为什么这么做，代价是什么。_")
    L.append("")
    L.append("1. ")
    L.append("2. ")
    L.append("3. ")
    L.append("")

    L.append("## 6. 可迁移清单")
    L.append("")
    L.append("_手写，必填。每条标注：是什么 / 适用前提 / 复现难度。挑一条做最小复现，结论写回这里。_")
    L.append("")
    L.append("| 可迁移点 | 适用前提 | 复现难度 | 复现结论 |")
    L.append("| --- | --- | --- | --- |")
    L.append("|  |  |  |  |")
    L.append("")

    L.append("## 附录 · 建议的下一步")
    L.append("")
    for i, s in enumerate(steps, 1):
        L.append(f"### {i}. {s.title}")
        L.append("")
        L.append(s.why)
        L.append("")
        if s.commands:
            L.append("```bash")
            L.extend(s.commands)
            L.append("```")
            L.append("")
        if s.fallback:
            L.append(f"> 失败时：{s.fallback}")
            L.append("")
    return "\n".join(L) + "\n"


def render_compare(rows: list[dict]) -> str:
    L = ["# 横向对比", "", "| 目标 | Unity | 后端 | 平台 | 体积 | 热更 | 渲染 | 网络 | 资源管理 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        fw = r.get("frameworks", [])

        def cat(c: str) -> str:
            names = [f["name"] for f in fw if f["category"] == c]
            return "、".join(names) if names else "—"

        name = str(r.get("target", "?")).rstrip("/").rsplit("/", 1)[-1]
        L.append(
            f"| {name} | {r.get('unity_version') or '?'} | {r.get('backend')} | {r.get('platform')} "
            f"| {human(int(r.get('total_bytes') or 0))} | {cat('hotfix')} | {cat('render')} "
            f"| {cat('net')} | {cat('asset')} |"
        )
    L += ["", "> 单个项目的选择可能是历史包袱，多个项目的共同选择才是行业经验。"]
    return "\n".join(L) + "\n"
