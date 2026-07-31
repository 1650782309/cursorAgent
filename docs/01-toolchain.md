# 工具矩阵

按流水线阶段组织。标注 `★` 的是这一格里的首选。

## ① 侦察

| 工具 | 用途 | 备注 |
| --- | --- | --- |
| ★ `urecon fingerprint` | 版本/后端/框架/保护一次性识别 | 本仓库提供 |
| DIE (Detect It Easy) | 壳、加固、编译器识别 | Windows/Linux/macOS 都有 |
| `strings` + `rabin2 -I` | 快速看导入表和特征串 | radare2 自带 |
| jadx | Android 侧 Java 层、加固壳判断 | APK 必看 `MainActivity` 与 `UnityPlayer` 的关系 |
| `apkanalyzer` / `aapt2 dump badging` | APK 元信息、abi、so 列表 | Android SDK 自带 |

## ② 资源提取

| 工具 | 用途 | 备注 |
| --- | --- | --- |
| ★ AssetRipper | 导出**可用 Unity 打开的工程**，含场景、prefab、材质 | 学工程结构的第一工具，比只导图片的强太多 |
| ★ UnityPy | 脚本化批量处理，做自动清点/自定义解密 | Python 库，`urecon inventory` 基于它 |
| AssetStudio(Mod) | GUI 快速预览、导出模型动画 | 看 mesh/animation 最顺手 |
| UABEA | 单个资源的字段级编辑与查看 | 需要精确改某个字段时用 |
| Il2CppDumper 的 `dummy dll` | 给 AssetRipper 恢复 MonoBehaviour 字段名 | IL2CPP 工程必备的前置步骤 |
| TypeTreeGenerator | 生成 TypeTree 给无 TypeTree 的 bundle | Unity 打包时剥离 TypeTree 时用 |

## ③ 代码还原

### Mono 路线

| 工具 | 用途 |
| --- | --- |
| ★ ILSpy / `ilspycmd` | 批量反编译成 `.cs`，可进 git 做版本 diff |
| dnSpy / dnSpyEx | 边看边改边调试，断点下在 IL 上 |
| dotPeek | 生成 PDB 后可用 VS 调试 |
| de4dot | 处理常见 .NET 混淆 |

### IL2CPP 路线

| 工具 | 用途 |
| --- | --- |
| ★ Il2CppDumper | 出 `dump.cs`（类/字段/方法+RVA）和 `DummyDll` |
| ★ Il2CppInspector | 出 IDA/Ghidra 脚本、C++ 头、Unity 工程脚手架 |
| Cpp2IL | 不依赖 metadata 结构的解析，新版本兼容性常更好 |
| IDA Pro / Ghidra | 真正读逻辑的地方，导入符号脚本后可读性大幅提升 |
| il2cpp_ghidra_scripts | Ghidra 侧的类型恢复 |

### 热更层

| 形态 | 工具 |
| --- | --- |
| HybridCLR | 热更 DLL 在 bundle 里，抽出后当普通 IL 反编译 |
| ILRuntime | 同上 |
| xLua / tolua / sLua | `unluac` / `luadec` / `ljd`（LuaJIT）；先确认是否改了字节码格式 |
| Puerts / JS | 找 `.js`/`.mjs` 资源，多数只做了 uglify |

## ④ 运行时

| 工具 | 用途 | 平台 |
| --- | --- | --- |
| ★ BepInEx + UnityExplorer | 运行时对象树、组件字段实时查看与修改 | PC，Mono/IL2CPP 都支持 |
| MelonLoader | 同类 modding 框架，部分游戏兼容性更好 | PC |
| ★ Frida | Hook native 层，dump 内存、追加密函数 | Android/iOS/PC，移动端首选 |
| Il2CppDumper memory 模式 | metadata 加密时从内存 dump | 全平台 |
| RenderDoc | 抓帧，看渲染管线、drawcall、shader、RT 布局 | PC/Android |
| ★ Unity Profiler (attach) | Development build 时直连，看真实性能分布 | 少见但极有价值 |
| Nsight / Xcode GPU Capture | 移动端 GPU 深度分析 | Android / iOS |
| mitmproxy / Charles / Wireshark | 网络协议 | 配合 proto 还原 |

## ⑤ 协议与数据

| 工具 | 用途 |
| --- | --- |
| ★ protobuf-inspector / blackboxprotobuf | 无 proto 定义时推断 protobuf 结构 |
| pbtk | 从 IL2CPP/APK 中直接提取 `.proto` 定义 |
| Kaitai Struct | 自定义二进制格式的建模与解析 |
| `urecon report` | 把上述发现汇总成结构化报告 |

## ⑥ 归档与对比

| 工具 | 用途 |
| --- | --- |
| git | 反编译产物入库，跨版本 `git diff` 看开发者改了什么——**这是最被低估的技巧** |
| `ripgrep` | 在几十万行 dump.cs 里定位关键类 |
| Obsidian / 任意 md 笔记 | `urecon report` 的输出直接放进去 |

## 环境建议

- 逆向环境放虚拟机或独立容器，不要在日常开发机上跑未知二进制。
- 每个目标建独立目录：`targets/<game>/{original,extracted,decompiled,notes,artifacts}`，`urecon` 默认按这个布局输出。
- 反编译产物入 git，但**不要 push 到公开仓库**，见 [07-legal.md](07-legal.md)。
