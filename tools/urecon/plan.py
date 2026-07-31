"""根据指纹产出针对性的下一步工具流。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fingerprint import Fingerprint


@dataclass
class Step:
    title: str
    why: str
    commands: list[str] = field(default_factory=list)
    fallback: str = ""


def build(fp: Fingerprint, target: str = "<target>") -> list[Step]:
    steps: list[Step] = []
    data = fp.data_dir or "<Game>_Data"

    if fp.platform == "android" or fp.source_kind == "apk":
        steps.append(Step(
            "解包 APK",
            "先把 so 与 assets 落到磁盘，后续所有工具都基于解包后的目录。",
            [f"unzip -o {target} -d apk/", "ls apk/lib/*/ apk/assets/bin/Data/"],
            "看到 libjiagu/libDexHelper 等加固 so 说明 libil2cpp.so 是壳，需先脱壳（frida-dexdump / BlackDex）。",
        ))

    if fp.backend.startswith("il2cpp"):
        if fp.metadata_encrypted:
            steps.append(Step(
                "从内存 dump metadata",
                "静态 metadata 被加密，逆算法性价比低；游戏运行时一定会解密。",
                [
                    "frida -U -f <package> -l scripts/dump_metadata.js --no-pause",
                    "# 或 PC：进主菜单后用 Il2CppDumper 的内存模式",
                ],
                "dump 出来的文件头应为 AF 1B B1 FA，拿到后走标准 Il2CppDumper 流程。",
            ))
        steps.append(Step(
            "Il2CppDumper 提取符号",
            "把 metadata 里的类型信息贴回无符号的原生二进制，这是 IL2CPP 逆向的地基。",
            [
                f"Il2CppDumper {'libil2cpp.so' if fp.platform == 'android' else 'GameAssembly.dll'} "
                f"{fp.metadata_path or 'global-metadata.dat'} decompiled/",
                "rg 'class .*Manager' decompiled/dump.cs | head -50",
            ],
            "报错先换 Cpp2IL（对新版/魔改 metadata 容错更好），再考虑手动指定 CodeRegistration 地址。",
        ))
        steps.append(Step(
            "导入反汇编器恢复可读性",
            "有符号的 IDA/Ghidra 才能真正读逻辑；无符号状态下读汇编基本是浪费时间。",
            [
                "# IDA: File → Script file → decompiled/ida_with_struct_py3.py",
                "# Ghidra: 配合 Il2CppInspector 生成的 C++ 头导入结构体",
            ],
        ))
    elif fp.backend == "mono":
        steps.append(Step(
            "反编译托管程序集并入库",
            "Mono 后端下 IL 反编译几乎等于拿到源码；入 git 后跨版本 diff 能直接看出开发者改了什么。",
            [
                f"ilspycmd -p -o decompiled/ {data}/Managed/Assembly-CSharp.dll",
                "cd decompiled && git init && git add -A && git commit -m 'baseline'",
            ],
            "遇到混淆先过一遍 de4dot。",
        ))
    else:
        steps.append(Step(
            "确认脚本后端",
            "后端未知会让后续所有选择都无从下手。",
            [f"ls {data}/Managed {data}/il2cpp_data 2>/dev/null", "rabin2 -I <主二进制>"],
        ))

    hotfix = [f for f in fp.frameworks if f.category == "hotfix"]
    if hotfix:
        names = "、".join(f.name for f in hotfix)
        steps.append(Step(
            f"处理热更层（{names}）",
            "热更方案下真正的业务逻辑通常不在主二进制里，只逆 AOT 部分会看到一个空壳架构。",
            [
                f"urecon inventory {target} -o notes/   # 先在资源里定位 .dll.bytes / .lua / .js",
                "# HybridCLR / ILRuntime: 抽出热更 DLL → ilspycmd 反编译",
                "# xLua / tolua: 抽出 .lua.bytes → unluac / ljd 还原",
            ],
            "Lua 字节码解不开时，多半是改了 luac 头或指令表，用 Frida hook luaL_loadbuffer dump 明文。",
        ))

    steps.append(Step(
        "还原可打开的 Unity 工程",
        "场景层级、prefab 组织、ScriptableObject 配置、ProjectSettings 是纯粹的工程学样本，只有还原成工程才看得清。",
        [
            "AssetRipper --input original/ --output extracted/project"
            + (" --script-dll decompiled/DummyDll/" if fp.backend.startswith("il2cpp") else ""),
            f"# 用 Unity {fp.unity_version or '<对应版本>'} 打开 extracted/project",
        ],
    ))

    if fp.bundle_encryption in {"all", "partial"}:
        steps.append(Step(
            "破解自定义 bundle 容器",
            "检测到非标准 bundle 头，标准工具读不了，但引擎自己一定拿得到明文。",
            [
                "# 1) 先试固定偏移 / 单字节异或，看能否还原出 UnityFS 头",
                "# 2) 不行就 hook AssetBundle.LoadFromMemory，把入参 byte[] 落盘",
                "# 3) 还原出算法后写成 UnityPy 的解密回调做批量处理",
            ],
        ))

    steps.append(Step(
        "资源清点",
        "体积分布与分包粒度是打包策略最直观的证据。",
        [f"urecon inventory {target} -o notes/"],
    ))

    steps.append(Step(
        "提取模型与动画（可播放 FBX + 自动分类）",
        "按人物/物品/场景归档，学习角色绑定、动画拆分与场景拼装；可播放 FBX 依赖 AssetStudio。",
        [
            "urecon doctor",
            f"urecon extract {target} --format fbx",
            "# 产出在 extracted/models/{人物,物品,场景,...}/",
        ],
        "未装 AssetStudio 时会降级为 OBJ+动画 JSON，装好后设 URECON_ASSETSTUDIO 再跑一次即可。详见 docs/08-extract-models.md。",
    ))

    steps.append(Step(
        "运行时观测",
        "静态看结构，动态看行为。DontDestroyOnLoad 下的对象树基本等于对方的全局架构图。",
        (
            ["frida -U -f <package> -l scripts/trace_bundle.js"]
            if fp.platform == "android"
            else ["# 安装 BepInEx + UnityExplorer，游戏内 F7 打开对象树"]
        ) + ["# RenderDoc 抓一帧，看 pass 顺序、RT 格式、后处理链"],
    ))

    steps.append(Step(
        "归档与复现",
        "没有报告和最小复现的逆向只是围观，一周后什么都不会剩下。",
        [f"urecon report {target} -o notes/report.md"],
        "报告最后两节（三个『我没想到』+ 可迁移清单）必须手写，见 docs/06-learning-loop.md。",
    ))
    return steps
