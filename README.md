# Desktop AI Companion (Unity)

一个桌面 AI 虚拟人物陪伴软件的 **Unity 起步工程**。采用「大脑 / 身体」分离架构：
AI 对话逻辑与角色渲染彻底解耦，**2D（Spine）与 3D（VRM）通过统一抽象层可插拔**，
在线模型（千问 / DeepSeek）与本地模型（Ollama）走同一套 OpenAI 兼容接口。

> ⚠️ 本仓库是**脚手架**：提供完整的工程结构、C# 脚本、配置模板与装配方式。
> 由于 Spine / VRM / 透明窗口依赖第三方包，需按下文安装并开启对应编译宏后才是完整功能。
> 未安装这些包时工程**仍可编译运行**（使用占位实现），可先跑通 AI 对话链路。

---

## 架构总览

```
┌──────────────── 大脑 Brain (Assets/Scripts/Brain, AI) ────────────────┐
│  PersonaConfig 人设 · MemoryStore 记忆 · DialogueManager 对话编排       │
│  EmotionParser 情绪解析                                                │
│  LLMManager → OpenAICompatibleProvider（千问 / DeepSeek / Ollama 统一） │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ 事件：OnEmotion / OnPartialReply / OnComplete
┌───────────────────────────────▼──────────────────────────────────────┐
│  身体 Body (Assets/Scripts/Rendering)                                  │
│  CharacterManager → ICharacterRenderer                                │
│      ├─ SpineCharacterRenderer  (2D, spine-unity)                     │
│      └─ VrmCharacterRenderer    (3D, UniVRM)                          │
├───────────────────────────────────────────────────────────────────────┤
│  窗口 Window (Assets/Scripts/Window)                                   │
│  DesktopWindowManager + ClickThroughController (UniWindowController)   │
│  透明 / 置顶 / 点击穿透（只有人物区域可点，其余穿透到桌面）              │
└───────────────────────────────────────────────────────────────────────┘
```

**为什么这样分层**：未来若要新增角色形态、换 2D/3D、甚至替换渲染方案，
只需实现 `ICharacterRenderer`，大脑层（AI/人设/记忆/情绪）完全不动。

---

## 环境要求

- Unity **6 LTS（6000.0.x）**（用其它 LTS 打开会提示升级，脚本本身兼容）
- 目标平台：Windows / macOS 桌面

---

## 安装步骤

### 1. 打开工程
用 Unity Hub 添加本仓库根目录作为工程并打开。首次会自动拉取 `Packages/manifest.json`
里的依赖（含 **Newtonsoft Json**，脚本 JSON 解析依赖它）。

### 2. 安装第三方渲染/窗口包（按需）

| 功能 | 包 | 安装方式 | 编译宏 |
|------|----|---------|--------|
| 3D 角色 | **UniVRM** | Package Manager → Add package from git URL：<br>`https://github.com/vrm-c/UniVRM.git?path=/Assets/VRM10#v0.128.0` | `UNIVRM_PRESENT` |
| 2D 角色 | **spine-unity** | 从 Esoteric 官网下载对应 Unity 版本的 `.unitypackage` 导入（需 Spine 授权） | `SPINE_UNITY` |
| 透明窗口 | **UniWindowController** | 从 GitHub `kirurobo/UniWindowController` 下载 `.unitypackage` 导入 | `UNIWINDOW_PRESENT` |

> 版本号以各仓库最新 Release 为准，上面仅示例。

### 3. 开启编译宏
`Edit → Project Settings → Player → Other Settings → Scripting Define Symbols`，
按已安装的包添加：`UNIVRM_PRESENT;SPINE_UNITY;UNIWINDOW_PRESENT`（只加装了的）。
未添加时对应后端走占位实现，不影响编译。

### 4. Windows 透明窗口设置
`Player Settings`：
- Resolution and Presentation → Fullscreen Mode 设为 **Windowed**
- Rendering → 取消勾选 **Use DXGI Flip Model Swapchain**（透明必需）

---

## 场景装配

1. 新建场景，保留一个 `Main Camera`。
2. 新建空物体 `Character`，挂 `CharacterManager`（`Assets/Scripts/Rendering`），
   把相机拖到其 `Camera` 字段。
3. 新建空物体 `App`，挂 `AppBootstrap`（`Assets/Scripts/App`），
   把 `Character` 拖到 `Character` 字段，设置默认 `Kind`/`ResourcePath`。
4. 新建空物体 `UI`，挂 `ChatDebugUI`，把 `App` 拖上去（开箱即用的调试对话框）。
5. （启用透明窗口时）把 UniWindowController 的 Prefab 拖进场景，
   并在某物体上挂 `DesktopWindowManager` + `ClickThroughController`，关联 `CharacterManager`。

---

## 配置模型与人设

编辑 `Assets/StreamingAssets/Config/`：

- `model_config.json`：内置 `deepseek` / `qwen` / `ollama` 三个供应商，改 `active` 切换，
  填入 `apiKey`。**建议把带真实 key 的文件另存为 `model_config.local.json`**
  （已在 `.gitignore` 忽略，避免泄露）。
- `persona.json`：角色名字、性格与情绪标注规则。

模型接入说明：
- **DeepSeek**：`https://api.deepseek.com/v1`，`model=deepseek-chat`。
- **千问（DashScope 兼容模式）**：`https://dashscope.aliyuncs.com/compatible-mode/v1`，`model=qwen-plus` 等。
- **本地 Ollama**：先 `ollama run qwen2.5`，地址 `http://localhost:11434/v1`。

三者都是 OpenAI 兼容接口，由 `OpenAICompatibleProvider` 一份代码统一处理流式输出。

---

## 情绪 → 表情联动

人设会要求模型在回复前输出 `[emotion:happy]` 这样的标签，`EmotionParser` 解析后：
- 通过 `DialogueManager.OnEmotion` 事件驱动 `CharacterManager.SetExpression`；
- VRM 映射到标准表情预设，Spine 映射到情绪动画；
- 展示给用户的正文会自动去掉该标签。

---

## 目录结构

```
Assets/Scripts/
  Core/        Emotion, CharacterAsset, ICharacterRenderer, MainThreadDispatcher
  Rendering/   CharacterManager, SpineCharacterRenderer, VrmCharacterRenderer
  AI/          ChatMessage, LLMConfig, ILLMProvider, OpenAICompatibleProvider, LLMManager
  Brain/       PersonaConfig, EmotionParser, MemoryStore, DialogueManager
  Window/      DesktopWindowManager, ClickThroughController
  App/         AppBootstrap, PersonaLoader
  UI/          ChatDebugUI
Assets/StreamingAssets/Config/   model_config.json, persona.json
```

---

## 后续路线（Roadmap）

- [ ] 语音：ASR（sherpa-onnx / whisper）+ TTS（edge-tts / GPT-SoVITS），TTS 音频驱动 VRM viseme 口型
- [ ] 长期记忆：sqlite + 向量检索（当前为 JSON 短期记忆）
- [ ] 美观对话气泡（uGUI / TextMeshPro 替换 IMGUI 调试框）
- [ ] 多角色管理与形态切换 UI
- [ ] 系统托盘、开机自启、拖动与右键菜单
- [ ] 动作系统：把 Mixamo/自制动画接到 VRM Animator，情绪→动作状态机
