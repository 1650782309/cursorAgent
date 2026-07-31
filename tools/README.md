# urecon

Unity 逆向学习流水线的编排器。它不做反编译，也不逆算法——那些交给 Il2CppDumper / ILSpy / IDA。
它负责把每次逆向里最枯燥、最容易偷懒的部分自动化：识别目标、清点资源、生成下一步待办、把产出固化成同一种格式。

## 安装

```bash
pip install -e tools/                # 核心功能，零依赖
pip install -e "tools/[assets]"      # 加上 UnityPy，解锁对象级资源清点
```

## 用法

```bash
urecon init targets/foo --source /games/Foo   # 建工作区
urecon fingerprint targets/foo                # 版本 / 后端 / 框架 / 保护
urecon inventory   targets/foo                # 容器与对象清点，出 CSV
urecon extract     targets/foo --format fbx   # 模型/动画 → 人物·物品·场景
urecon doctor                                 # 检查 AssetStudio / UnityPy
urecon plan        targets/foo                # 针对该目标的下一步工具流
urecon report      targets/foo                # 汇总 Markdown 报告
urecon compare     targets/*/urecon.json      # 多目标横向对比
```

可播放 FBX 需要外部工具（UnityPy 只能出 OBJ）。安装 AssetStudio 后：

```bash
# Windows PowerShell
$env:URECON_ASSETSTUDIO = "D:\tools\AssetStudio\AssetStudio.CLI.exe"
urecon extract targets/foo --format fbx
```

分类规则与降级策略见 [../docs/08-extract-models.md](../docs/08-extract-models.md)。

`fingerprint` 和后续命令都能直接接受原始游戏目录或 APK，不建工作区也能跑：

```bash
urecon fingerprint /games/Foo/Foo_Data --json
urecon fingerprint game.apk
```

## 它能识别什么

- Unity 版本、目标平台与 ABI
- 脚本后端：Mono / IL2CPP / 混合
- `global-metadata.dat` 是否加密、metadata 版本
- 60+ 种框架与中间件：HybridCLR、xLua、ILRuntime、Puerts、URP/HDRP、FairyGUI、Addressables、YooAsset、DOTS、UniTask、Photon、KCP、FMOD、加固与反作弊组件等
- AssetBundle 容器是否为标准 `UnityFS`，非标准时给出偏移/加密判断

识别结果驱动 `plan`：Mono 项目不会让你去跑 Il2CppDumper，metadata 加密时会直接把你导向运行时 dump 路线。

## 设计取舍

- **零必需依赖**：核心识别只用标准库，任何机器上都能跑。UnityPy 是可选增强。
- **只读目标**：所有输出落到工作区，不碰 `original/`。
- **失败不中断**：单个容器解析不了就记下错误继续，最终在报告里体现为"解析失败 N 个"——这本身就是加密强度的信号。
- **JSON 优先**：每步产出都可机器读取，`compare` 才能做横向分析。

完整方法论见 [../docs/00-overview.md](../docs/00-overview.md)。
