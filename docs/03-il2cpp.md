# IL2CPP 专题

## 它到底做了什么

Unity 把 C# 编译成 IL，再由 il2cpp 转译成 C++，最后编成原生二进制。托管世界的类型信息没有消失，而是被序列化进 `global-metadata.dat`：字符串字面量、类型定义、方法名、字段偏移全在里面。

所以逆向 IL2CPP 的本质是：**把 metadata 里的符号信息，重新贴回二进制里那些没有名字的函数上**。

```
GameAssembly.dll / libil2cpp.so   ← 机器码，无符号
global-metadata.dat                ← 符号表：类名、方法名、字段名、RVA 索引
        ↓ Il2CppDumper
dump.cs（人能读的类型全景） + script.json（给反汇编器的符号） + DummyDll（给 AssetRipper）
```

## 标准流程

```bash
Il2CppDumper GameAssembly.dll global-metadata.dat out/
```

然后在 IDA 里 `File → Script file → out/ida_with_struct_py3.py`，或 Ghidra 里跑对应脚本。跑完之后函数窗口里就是 `Namespace.Class$$Method` 这样的名字，可读性从 0 分到 70 分。

Ghidra 侧建议额外用 `Il2CppInspector` 生成 C++ 头再导入类型，结构体字段能直接还原，读代码时省掉大量偏移换算。

## 三个高频卡点

### 1. metadata 加密（magic 不是 `AF 1B B1 FA`）

不要去逆解密算法，那是最慢的路。游戏启动时一定会在内存里解密好，直接抓内存：

- **Android**：Frida hook `il2cpp_init`，之后在 `libil2cpp.so` 的数据段里搜 metadata magic 头，dump 出来
- **PC**：等游戏进主菜单，用 Il2CppDumper 的内存模式或 Cheat Engine 定位后 dump
- 有些加固只加密了头部若干字节，对比一个未加密的同版本 metadata 就能看出规律

dump 出的 metadata 通常能直接喂回 Il2CppDumper。

### 2. 版本不兼容 / 结构被改

Il2CppDumper 依赖 metadata 版本号（24.x / 27.x / 29.x …）。报错时按顺序试：

1. 更新到最新版 Il2CppDumper
2. 换 Cpp2IL —— 它不强依赖 metadata 结构，对新版本和魔改版本容错更好
3. 手动指定 metadata version 和 `CodeRegistration`/`MetadataRegistration` 地址（Il2CppDumper 支持手动输入）

### 3. 字符串加密

`dump.cs` 里字面量全是乱码时，通常是打包后做了字符串混淆。找 `Decrypt`/`GetString`/静态构造函数里的批量解密循环，用 Frida hook 住这个函数，把入参出参全打出来，比静态还原快一个数量级。

## HybridCLR

现在国内 IL2CPP 手游主流的热更方案。特征：`dump.cs` 里出现 `HybridCLR` 命名空间，或 StreamingAssets 里有 `.dll.bytes`。

- AOT 部分在 `GameAssembly`，走上面的流程
- **热更部分是完整的 .NET DLL**，从 bundle 里抽出来后用 ILSpy 反编译，可读性接近源码

所以遇到 HybridCLR 项目要高兴：真正的业务逻辑往往全在热更 DLL 里，反而比纯 AOT 好读。ILRuntime 同理。

## 从 dump.cs 里高效找东西

`dump.cs` 常有几十万行，别顺读。带着问题 grep：

```bash
rg "class .*Manager" dump.cs | head -50           # 全局架构
rg -n "class .*(Battle|Combat|Skill)" dump.cs      # 战斗系统
rg -n "(UniTask|Addressables|DOTween|Photon)" dump.cs   # 用了哪些中间件
rg -n "\[Serializable\]" -A5 dump.cs               # 配置数据结构
rg -n "class .*(Net|Socket|Protocol|Msg)" dump.cs  # 网络层
```

看到一个感兴趣的方法，记下它的 RVA，回 IDA 跳过去读实现。

**读架构不需要读实现**：类名、字段名、方法签名、继承关系这四样，已经足够还原出一个团队的分层设计和模块划分。这才是逆向学习的主要价值来源，而不是某个函数的具体算法。
