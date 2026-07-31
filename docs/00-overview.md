# Unity 工程逆向学习工具流 · 总览

## 这套工具流要解决的问题

看到一款做得好的 Unity 游戏，想搞清楚："它的资源怎么组织的？渲染管线怎么改的？热更新怎么做的？战斗逻辑跑在哪一层？网络协议长什么样？"
靠猜没有意义，靠一次性的手工拆包又无法沉淀。这里定义的是一条**可重复、可自动化、可产出结构化笔记**的流水线。

目标不是"把游戏还原出来能跑"，而是**把别人的工程决策提炼成自己能复用的知识**。

## 五个阶段

```
① 侦察 Recon        → 这是什么引擎/版本/脚本后端/有没有加壳，决定后面走哪条路
② 静态解构 Static   → 拆资源、反编译代码、还原工程结构
③ 动态观测 Dynamic  → 注入运行时，看真实的对象树、调用栈、GPU 帧、网络包
④ 结构化归档 Model  → 把发现写成机器可读的清单 + 人类可读的报告
⑤ 复现验证 Rebuild  → 在自己的空工程里做最小复现，确认"我真的学会了"
```

第 ⑤ 步是很多人跳过的一步，但它才是学习闭环。前四步只是"看见"，第五步才是"学会"。

## 决策主干

侦察阶段的两个判断决定后续所有工具选择：

**判断一：脚本后端**

| 特征文件 | 后端 | 代码路径难度 |
| --- | --- | --- |
| `Managed/Assembly-CSharp.dll` | Mono | 低。IL 反编译几乎等于拿到源码 |
| `GameAssembly.dll` / `libil2cpp.so` + `global-metadata.dat` | IL2CPP | 中高。需要 dump 元数据后配合反汇编器 |
| 上述都有 + `HybridCLR`/`hybridclr` 字样 | IL2CPP + HybridCLR 热更 | 主体 AOT，热更 DLL 在资源里，两条路都要走 |
| `xlua`/`tolua`/`slua`/`.lua.bytes` | Lua 热更 | 逻辑在 Lua 里，重点变成 Lua 字节码还原 |
| `ILRuntime` | ILRuntime 热更 | 热更 DLL 在 AssetBundle 里，正常 IL 反编译 |

**判断二：资源保护强度**

| 现象 | 含义 | 对策 |
| --- | --- | --- |
| AssetBundle 头部是明文 `UnityFS` | 无加密 | 直接 UnityPy / AssetStudio |
| 头部非 `UnityFS` 但有固定 magic | 整包加密或自定义容器 | 逆 `AssetBundle.LoadFromMemory` 的调用方，找解密函数 |
| 头部 `UnityFS` 但 block 解不开 | 改了 LZ4/LZMA 或 UnityFS 结构 | 逆 il2cpp 里的 bundle 加载路径，或运行时 hook dump |
| `global-metadata.dat` 头部 magic 不是 `AF 1B B1 FA` | metadata 加密 | 运行时从内存 dump（Frida / Il2CppDumper 的 memory 模式）|

一句话：**静态拆不开就上运行时 dump**。运行时游戏自己一定会解密，把解密后的内存抓下来永远比逆算法快。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [01-toolchain.md](01-toolchain.md) | 工具矩阵，每个环节用什么、为什么 |
| [02-workflow.md](02-workflow.md) | 完整 SOP，一步步的命令级流程 |
| [03-il2cpp.md](03-il2cpp.md) | IL2CPP 专题：dump、符号恢复、加密 metadata |
| [04-runtime.md](04-runtime.md) | 运行时观测：BepInEx / MelonLoader / Frida / RenderDoc |
| [05-assets.md](05-assets.md) | 资源与 AssetBundle 管线分析 |
| [06-learning-loop.md](06-learning-loop.md) | 怎么把逆向结果变成自己的技术积累 |
| [07-legal.md](07-legal.md) | 合规边界，先读这个 |

## 配套 CLI

`tools/urecon` 是这条流水线的编排器，负责自动化里最枯燥的部分：识别、清点、生成待办。

```bash
pip install -e tools/
urecon fingerprint /path/to/Game            # 识别引擎版本、后端、框架、保护
urecon inventory   /path/to/Game -o out/    # 清点资源与 bundle
urecon plan        /path/to/Game            # 根据指纹产出针对性的下一步工具流
urecon report      /path/to/Game -o out/    # 汇总成 markdown 报告
```

它不替你做反编译和逆算法——那些交给专业工具。它做的是**把每次逆向的产出固化成同一种格式**，这样十个项目看下来能横向对比，而不是十份散落的截图。
