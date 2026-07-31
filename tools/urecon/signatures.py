"""第三方框架 / 中间件的识别特征。

每条特征给出两类线索：
  files   —— 文件名（不含路径）上的子串，命中即算强证据
  strings —— 需要在二进制里搜索的字节串，命中算中等证据
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Signature:
    key: str
    name: str
    category: str
    files: tuple[str, ...] = ()
    strings: tuple[str, ...] = ()
    note: str = ""


SIGNATURES: tuple[Signature, ...] = (
    # ---- 热更新方案 ----
    Signature(
        "hybridclr", "HybridCLR", "hotfix",
        files=("hybridclr",),
        strings=("HybridCLR", "hybridclr_"),
        note="AOT+解释器混合热更。业务逻辑多在热更 DLL 里，抽出后可直接 ILSpy 反编译。",
    ),
    Signature(
        "ilruntime", "ILRuntime", "hotfix",
        files=("ilruntime",),
        strings=("ILRuntime.Runtime",),
        note="热更 DLL 藏在 AssetBundle 中，取出后按普通 IL 反编译。",
    ),
    Signature(
        "xlua", "xLua", "hotfix",
        files=("xlua",),
        strings=("XLua.LuaEnv", "xlua"),
        note="逻辑在 Lua 层，重点转向 Lua 字节码还原（unluac / ljd）。",
    ),
    Signature(
        "tolua", "toLua", "hotfix",
        files=("tolua",),
        strings=("LuaInterface", "tolua_"),
    ),
    Signature(
        "slua", "sLua", "hotfix",
        files=("slua",),
        strings=("SLua.LuaSvr",),
    ),
    Signature(
        "puerts", "PuerTS", "hotfix",
        files=("puerts",),
        strings=("Puerts.JsEnv", "puerts"),
        note="逻辑在 JS/TS 层，找 .js/.mjs 资源，多数只做了 uglify。",
    ),
    Signature(
        "lua_generic", "Lua 运行时", "hotfix",
        files=("lua51", "lua53", "luajit"),
        strings=("$LuaJIT", "Lua 5.1", "Lua 5.3", "Lua 5.4"),
    ),

    # ---- 渲染 ----
    Signature(
        "urp", "Universal RP", "render",
        files=("unity.renderpipelines.universal",),
        strings=("UnityEngine.Rendering.Universal",),
    ),
    Signature(
        "hdrp", "HDRP", "render",
        files=("unity.renderpipelines.highdefinition",),
        strings=("UnityEngine.Rendering.HighDefinition",),
    ),
    Signature(
        "postprocessing", "Post Processing Stack v2", "render",
        files=("unity.postprocessing",),
        strings=("UnityEngine.Rendering.PostProcessing",),
    ),
    Signature(
        "amplify", "Amplify Shader/Occlusion", "render",
        files=("amplify",), strings=("AmplifyShaderEditor", "AmplifyOcclusion"),
    ),

    # ---- UI ----
    Signature(
        "fairygui", "FairyGUI", "ui",
        files=("fairygui",), strings=("FairyGUI.GComponent",),
    ),
    Signature(
        "tmp", "TextMeshPro", "ui",
        files=("unity.textmeshpro",), strings=("TMPro.TextMeshProUGUI",),
    ),
    Signature(
        "uitoolkit", "UI Toolkit", "ui",
        files=("unityengine.uielementsmodule",), strings=("UnityEngine.UIElements",),
    ),
    Signature(
        "spine", "Spine", "ui",
        files=("spine-unity", "spine-csharp"), strings=("Spine.SkeletonData",),
    ),
    Signature(
        "live2d", "Live2D Cubism", "ui",
        files=("live2d", "cubism"), strings=("Live2D.Cubism",),
    ),

    # ---- 网络 ----
    Signature(
        "photon", "Photon", "net",
        files=("photon",), strings=("Photon.Pun", "ExitGames.Client.Photon"),
    ),
    Signature(
        "mirror", "Mirror", "net",
        files=("mirror",), strings=("Mirror.NetworkBehaviour",),
    ),
    Signature(
        "netcode", "Netcode for GameObjects", "net",
        files=("unity.netcode",), strings=("Unity.Netcode",),
    ),
    Signature(
        "kcp", "KCP", "net",
        files=("kcp",), strings=("kcp_", "IKCPCB", "KcpChannel"),
        note="常见于帧同步/低延迟对战，配合自研可靠 UDP 层。",
    ),
    Signature(
        "besthttp", "BestHTTP", "net",
        files=("besthttp",), strings=("BestHTTP.HTTPRequest",),
    ),
    Signature(
        "protobuf", "Protobuf", "net",
        files=("google.protobuf", "protobuf-net"),
        strings=("google.protobuf", "Google.Protobuf.IMessage"),
        note="协议还原用 pbtk 提取 .proto，或 blackboxprotobuf 推断。",
    ),
    Signature(
        "grpc", "gRPC", "net", files=("grpc.core",), strings=("Grpc.Core",),
    ),

    # ---- 资源 / 构建 ----
    Signature(
        "addressables", "Addressables", "asset",
        files=("unity.addressables", "catalog.json", "catalog.bin"),
        strings=("UnityEngine.AddressableAssets",),
        note="看 catalog 的拆分方式，能反推热更粒度设计。",
    ),
    Signature(
        "yooasset", "YooAsset", "asset",
        files=("yooasset",), strings=("YooAsset.",),
    ),
    Signature(
        "xasset", "xasset", "asset", files=("xasset",), strings=("xasset",),
    ),

    # ---- 架构 / 工具库 ----
    Signature(
        "dots", "DOTS / Entities", "arch",
        files=("unity.entities", "unity.burst"),
        strings=("Unity.Entities.World", "Unity.Burst"),
        note="用了 ECS 说明有明确的性能诉求，值得重点看数据布局。",
    ),
    Signature(
        "jobs", "Job System / Collections", "arch",
        files=("unity.collections", "unity.jobs"), strings=("Unity.Jobs.IJob",),
    ),
    Signature(
        "unitask", "UniTask", "arch",
        files=("unitask",), strings=("Cysharp.Threading.Tasks",),
    ),
    Signature(
        "zenject", "Zenject / Extenject", "arch",
        files=("zenject",), strings=("Zenject.DiContainer",),
    ),
    Signature(
        "vcontainer", "VContainer", "arch",
        files=("vcontainer",), strings=("VContainer.IObjectResolver",),
    ),
    Signature(
        "odin", "Odin Inspector", "arch",
        files=("sirenix",), strings=("Sirenix.OdinInspector",),
    ),
    Signature(
        "dotween", "DOTween", "arch",
        files=("dotween",), strings=("DG.Tweening",),
    ),
    Signature(
        "memorypack", "MemoryPack / MessagePack", "arch",
        files=("memorypack", "messagepack"),
        strings=("MemoryPack.", "MessagePack.MessagePackSerializer"),
    ),
    Signature(
        "luban", "Luban 配置表", "arch",
        files=("luban",), strings=("Luban.",),
    ),

    # ---- SDK / 运营 ----
    Signature(
        "firebase", "Firebase", "sdk",
        files=("firebase",), strings=("com.google.firebase",),
    ),
    Signature(
        "appsflyer", "AppsFlyer", "sdk",
        files=("appsflyer",), strings=("appsflyer",),
    ),
    Signature(
        "adjust", "Adjust", "sdk", files=("adjust",), strings=("com.adjust.sdk",),
    ),
    Signature(
        "fmod", "FMOD", "sdk", files=("fmod",), strings=("FMOD.Studio",),
    ),
    Signature(
        "wwise", "Wwise", "sdk", files=("akSoundEngine", "wwise"), strings=("AkSoundEngine",),
    ),

    # ---- 加固 / 反作弊 ----
    Signature(
        "il2cpp_obfuscator", "IL2CPP 加固/混淆", "protect",
        files=("obfuscator",), strings=("Beebyte", "Obfuscator.Runtime"),
    ),
    Signature(
        "jiagu", "Android 加固壳", "protect",
        files=("libjiagu", "libdexhelper", "libshella", "libexec", "libnesec", "libtprt"),
        note="需先脱壳才能拿到真实 libil2cpp.so。",
    ),
    Signature(
        "easyanticheat", "EasyAntiCheat", "protect",
        files=("easyanticheat",), strings=("EasyAntiCheat",),
    ),
    Signature(
        "battleye", "BattlEye", "protect", files=("battleye", "beclient"),
    ),
)


BY_CATEGORY: dict[str, list[Signature]] = {}
for _sig in SIGNATURES:
    BY_CATEGORY.setdefault(_sig.category, []).append(_sig)

CATEGORY_LABEL = {
    "hotfix": "热更新 / 脚本层",
    "render": "渲染",
    "ui": "UI",
    "net": "网络",
    "asset": "资源管理",
    "arch": "架构 / 工具库",
    "sdk": "第三方 SDK",
    "protect": "加固 / 反作弊",
}
