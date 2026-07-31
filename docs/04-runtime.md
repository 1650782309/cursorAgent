# 运行时观测

静态分析告诉你"代码里写了什么"，运行时告诉你"实际发生了什么"。后者对学习工程实践更有价值——因为架构图骗人，运行时的对象树不骗人。

## PC：BepInEx + UnityExplorer

安装后启动游戏，`F7` 呼出。核心视图：

**Object Explorer** — 场景对象树。重点看：
- `DontDestroyOnLoad` 场景下挂了什么。这是整个游戏的全局架构，通常十几个 Manager 单例，一眼看出模块划分
- UI 根节点结构：几个 Canvas、分层策略、是否 Screen Space Camera、CanvasScaler 配置
- 对象池父节点的规模，能看出内存策略

**Inspector** — 任意组件的字段实时值，可直接改。改一个值看游戏怎么变，是理解系统边界最快的方法。

**C# Console** — 直接在运行时执行 C#：

```csharp
// 列出所有 Manager 单例
foreach (var mb in Object.FindObjectsOfType<MonoBehaviour>())
    if (mb.GetType().Name.EndsWith("Manager")) Log(mb.GetType().FullName);

// 看当前渲染管线配置
Log(GraphicsSettings.currentRenderPipeline?.GetType().FullName ?? "Built-in");

// 看已加载的程序集，识别第三方中间件
foreach (var a in AppDomain.CurrentDomain.GetAssemblies()) Log(a.GetName().Name);
```

IL2CPP 游戏需要装 IL2CPP 版的 BepInEx（BepInEx 6 / Il2CppInterop），功能基本一致。

## 移动端：Frida

安装 frida-server 到已 root 的设备（或用 frida-gadget 重打包 APK）。

三个最有用的脚本方向：

**1. 追 AssetBundle 加载**——搞清楚它的资源加载策略与自定义解密：

```javascript
// hook il2cpp 导出的 bundle 加载入口，打出路径与栈
const il2cpp = Module.findBaseAddress("libil2cpp.so");
// 从 Il2CppDumper 的 script.json 里拿到目标方法 RVA
const rva = 0x1234560;
Interceptor.attach(il2cpp.add(rva), {
  onEnter(args) {
    console.log("LoadFromFile:", args[0].readUtf8String());
    console.log(Thread.backtrace(this.context, Backtracer.ACCURATE)
      .map(DebugSymbol.fromAddress).join("\n"));
  }
});
```

**2. dump 解密后的内容**——在解密函数返回处把 buffer 写盘。永远比逆算法快。

**3. SSL unpinning**——抓 HTTPS 时用现成的 unpinning 脚本，Unity 游戏多数走 UnityWebRequest 或 BestHTTP，前者用系统栈，后者可能自带证书校验，需要额外 hook。

## 渲染：RenderDoc

抓一帧，你能看到的比读一百行 shader 代码多：

| 看什么 | 学到什么 |
| --- | --- |
| Event Browser 的 pass 顺序 | 完整管线：depth prepass？shadow map 几级 cascade？后处理链顺序 |
| 每个 RT 的格式与分辨率 | 精度取舍、是否半分辨率做 bloom/SSAO |
| Drawcall 数量与 batch 情况 | 合批策略、SRP Batcher / GPU Instancing 用得怎么样 |
| 单个 drawcall 的 shader 源码 | 可直接看到反编译的 shader，学具体实现 |
| Mesh 输入布局 | 顶点数据压缩方案 |

移动端 GPU 深度指标（带宽、overdraw、tile 开销）用 Nsight（NV）、Snapdragon Profiler（高通）、Xcode GPU Capture（iOS）。

## Profiler

如果目标是 Development Build（偶尔会有，尤其是测试服包体），Unity Profiler 能直接 attach，那就等于拿到了对方的性能全景：每帧 CPU 分布、GC 分配、内存快照。这种情况不多，但值得每次都试一下。

Release build 也可以用 BepInEx 插件自己实现一个简易 tick 统计，或者用 `Time.frameCount` + 反射统计 Update 数量。

## 观测清单

每个目标至少回答这些问题，写进报告：

- [ ] 全局 Manager 有哪些，生命周期怎么管理
- [ ] 用了什么渲染管线，改了哪些 pass
- [ ] UI 框架是自研还是开源（FairyGUI / UGUI 自封装 / UIToolkit）
- [ ] 资源加载是 Addressables、自研 bundle 管理还是 Resources
- [ ] 逻辑层跑在 C# / Lua / 热更 DLL 的哪一层
- [ ] 有没有用 DOTS/ECS、JobSystem、Burst
- [ ] 网络层用了什么（自研 TCP / KCP / Mirror / Photon / Netcode）
- [ ] 帧同步还是状态同步（看有没有确定性数学库、定点数、帧缓冲队列）
