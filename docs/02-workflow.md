# 完整 SOP

以 PC 版 IL2CPP 游戏为主线，Android 差异在每步末尾标注。

## Step 0 · 建立工作区

```bash
urecon init targets/awesome-game --source /path/to/Game
```

产出目录：

```
targets/awesome-game/
  original/      # 只读原始文件（或软链）
  extracted/     # 资源导出
  decompiled/    # 代码反编译产物
  runtime/       # dump、日志、抓帧
  notes/         # 报告与手写笔记
  urecon.json    # 指纹与状态
```

原则：`original/` 永远不改。所有工具输出到别的目录，方便随时重来。

## Step 1 · 指纹识别

```bash
urecon fingerprint targets/awesome-game --json
```

关注四个结论：Unity 版本、脚本后端、热更方案、资源保护。它们决定了后面每一步。

同时手动确认一下：

```bash
ls Game_Data/StreamingAssets        # Addressables？自定义 bundle 目录？
ls Game_Data/Managed 2>/dev/null    # Mono 才有
xxd -l 32 Game_Data/il2cpp_data/Metadata/global-metadata.dat   # magic 应为 AF 1B B1 FA
```

> Android：`unzip -o game.apk -d apk/`，然后看 `apk/assets/bin/Data/`、`apk/lib/arm64-v8a/libil2cpp.so`。
> 如果 `libil2cpp.so` 不存在但有 `libmain.so` + 加固厂商 so（`libjiagu`、`libDexHelper` 等），先脱壳再继续。

## Step 2 · IL2CPP dump（Mono 项目跳到 Step 3）

```bash
Il2CppDumper GameAssembly.dll global-metadata.dat out/
```

产出：
- `dump.cs` — 全部类型与方法签名，带 RVA。**这是你后面最常 grep 的文件**
- `DummyDll/` — 空壳程序集，喂给 AssetRipper 用来恢复字段名
- `script.json` / `ida.py` — 导入 IDA/Ghidra 恢复符号

失败时的处理顺序：
1. 换 Cpp2IL 再试（对新版本 Unity 容错更好）
2. metadata 加密 → 走 [03-il2cpp.md](03-il2cpp.md) 的内存 dump 流程

## Step 3 · 代码反编译入库

Mono：

```bash
ilspycmd -p -o decompiled/ Game_Data/Managed/Assembly-CSharp.dll
cd decompiled && git init && git add -A && git commit -m "v1.2.3"
```

IL2CPP：`dump.cs` 直接入库即可。

**入库这一步不能省。** 游戏更新后重跑一遍，`git diff` 会直接告诉你开发者这个版本改了哪些类、加了什么字段——这比读一万行代码高效得多，也是了解一个团队工程演进最快的方式。

## Step 4 · 工程结构还原

```bash
AssetRipper --input original/ --output extracted/project --script-dll DummyDll/
```

用对应版本的 Unity 打开 `extracted/project`。此时能直接看到的东西：

- 场景层级与 prefab 组织方式
- 材质与 shader 变体
- Animator 状态机、Timeline
- ScriptableObject 配置的设计（很多团队的核心配置架构都在这里）
- Project Settings：图形层级、Quality 分级、物理层矩阵、Tag/Layer 规划

MonoBehaviour 的字段值能还原，方法体不能（IL2CPP 下），所以**逻辑看 `dump.cs`，数据与结构看还原工程**，两边对照。

## Step 5 · 资源与打包管线

```bash
urecon inventory targets/awesome-game -o notes/
```

输出资源类型分布、bundle 列表与体积、依赖关系。要回答的问题：

- 按什么维度分包（场景 / 功能模块 / 类型 / 图集）
- 图集怎么切、压缩格式选了什么（ASTC？ETC2？各分辨率档位）
- 是不是 Addressables，用了什么 label 与 group 策略
- 音频压缩与加载方式（Streaming / DecompressOnLoad）
- 首包多大，热更包多大，边界怎么划的

详见 [05-assets.md](05-assets.md)。

## Step 6 · 运行时观测

静态能看结构，动态才能看行为。

```bash
# PC：装 BepInEx 后放入 UnityExplorer
# 游戏内 F7 打开，实时看对象树、组件、字段
```

优先观测项：

| 观测 | 能学到什么 |
| --- | --- |
| DontDestroyOnLoad 下挂了哪些 Manager | 全局架构与生命周期设计 |
| UI Canvas 的分层与 raycast 设置 | UI 框架与性能取舍 |
| 每帧的 Update 数量、协程数 | 是否上了 ECS/JobSystem/自定义 tick |
| 对象池的规模与命中 | 内存策略 |
| RenderDoc 抓一帧 | 完整渲染管线：pass 顺序、RT 格式、后处理链、shadow 方案 |

移动端用 Frida：

```bash
frida -U -f com.foo.bar -l scripts/hook_bundle_load.js
```

详见 [04-runtime.md](04-runtime.md)。

## Step 7 · 网络协议

```bash
mitmproxy --mode transparent
```

HTTPS 有 SSL Pinning 时用 Frida 的 unpinning 脚本。长连接是自定义 TCP/KCP 的话，从 `dump.cs` 里搜 `Socket`、`Kcp`、`OnRecv` 找编解码入口，再用 Wireshark 对照。

protobuf 无定义时用 blackboxprotobuf 推断，或者用 pbtk 从二进制里直接提 `.proto`。

## Step 8 · 报告与复现

```bash
urecon report targets/awesome-game -o notes/report.md
```

报告是模板化的，但**最后一节必须手写**：挑 1–3 个值得学的点，在自己的空工程里做最小复现。

没有复现的逆向只是围观。详见 [06-learning-loop.md](06-learning-loop.md)。

## 一页速查

```
识别 → urecon fingerprint
 ├ Mono   → ilspycmd → git 入库
 └ IL2CPP → Il2CppDumper → dump.cs + DummyDll
              └ 失败 → Cpp2IL → 仍失败 → Frida 内存 dump
还原 → AssetRipper(+DummyDll) → 用同版本 Unity 打开
清点 → urecon inventory
动态 → BepInEx+UnityExplorer / Frida / RenderDoc
协议 → mitmproxy / Wireshark / blackboxprotobuf
归档 → urecon report → 最小复现工程
```
