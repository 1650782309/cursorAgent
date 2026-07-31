# Unity 工程逆向学习工具流

一套可重复的流水线，用来通过逆向别人的 Unity 游戏来学习工程技术——不是拆包看图，是把对方的工程决策提炼成自己能复用的知识。

> 先读 [合规边界](docs/07-legal.md)。这套东西的定位是技术学习与安全研究，产出应当是笔记和自己写的复现代码，不是从别人包里拷出来的文件。

## 五个阶段

```
① 侦察   引擎版本 / 脚本后端 / 热更方案 / 保护强度  → 决定后面走哪条路
② 静态   拆资源、反编译代码、还原成能打开的 Unity 工程
③ 动态   运行时对象树、GPU 抓帧、网络包
④ 归档   结构化报告，可跨项目横向对比
⑤ 复现   在空工程里做最小复现，确认真的学会了
```

第 ⑤ 步是多数人跳过的一步，也正是它把"围观"变成"学会"。

## 快速开始

```bash
pip install -e "tools/[assets]"       # 装 CLI（UnityPy 可选，不装则降级为文件级统计）
bash scripts/fetch_tools.sh           # 拉取 Il2CppDumper / AssetRipper / Cpp2IL / ILSpy 等

urecon init targets/foo --source /games/Foo
urecon fingerprint targets/foo        # 它是什么
urecon plan        targets/foo        # 针对它该怎么做
urecon inventory   targets/foo        # 资源与打包策略
urecon report      targets/foo        # 汇总成报告
```

`plan` 的输出是随目标变化的：Mono 项目不会让你去跑 Il2CppDumper，metadata 加密时会直接把你导向运行时内存 dump，检测到 HybridCLR 会提醒你真正的逻辑在热更 DLL 里。

不建工作区也能直接看：

```bash
urecon fingerprint /games/Foo --json
urecon fingerprint game.apk
```

## 仓库结构

```
docs/       方法论：工具矩阵、SOP、IL2CPP 专题、运行时、资源管线、学习闭环、合规
tools/      urecon CLI —— 流水线编排器（核心零依赖）
scripts/    Frida 脚本（metadata 内存 dump、bundle 追踪）与外部工具下载
targets/    每个逆向目标一个工作区（已 gitignore，不入库）
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [总览](docs/00-overview.md) | 五阶段模型与决策主干 |
| [工具矩阵](docs/01-toolchain.md) | 每个环节用什么、为什么 |
| [SOP](docs/02-workflow.md) | 命令级的完整流程 |
| [IL2CPP 专题](docs/03-il2cpp.md) | dump、符号恢复、加密 metadata、HybridCLR |
| [运行时观测](docs/04-runtime.md) | BepInEx / Frida / RenderDoc |
| [资源管线](docs/05-assets.md) | 分包、压缩、贴图格式、加密 bundle |
| [学习闭环](docs/06-learning-loop.md) | 报告模板与最小复现 |
| [合规边界](docs/07-legal.md) | 红线与实操约定 |

## 测试

```bash
cd tools && python3 -m unittest discover -s tests
```

测试用合成样本覆盖识别、清点、计划、报告全链路，不含任何真实游戏内容。
