# 项目上下文（给 Agent 读）

> 本文件汇总 Cloud Agent 会话中的技术选型与实现进度，供本地/云端 Agent 快速对齐上下文。
> 修改架构决策或完成里程碑后，请同步更新本文件。

---

## 项目是什么

桌面 AI 虚拟人物陪伴软件（桌宠 / VTuber 风格）：
- 悬浮在桌面上，透明窗口、可拖动、点击穿透
- 支持 2D（Spine）与 3D（VRM）角色，可插拔
- 接入在线模型（千问、DeepSeek）与本地模型（Ollama）
- 对话 → 情绪 → 表情/动作 → 语音朗读 + 口型

---

## 技术选型（已定，勿擅自改方向）

| 决策 | 结论 | 原因 |
|------|------|------|
| 总体路线 | **情况 B：直接用 Unity 起步** | 用户已确定 Unity 为终点，避免 Electron→Unity 双份开发 |
| 架构 | **大脑 / 身体分离** | AI/人设/记忆与渲染解耦，换 2D/3D/引擎时大脑不动 |
| 2D 角色 | **spine-unity**（Esoteric 官方） | Skin 换形态，动画表达情绪 |
| 3D 角色 | **UniVRM** | 标准表情 + viseme 口型 + SpringBone + LookAt |
| 桌面窗口 | **UniWindowController** | 透明/置顶/穿透/拖动，桌宠标准做法 |
| AI 接入 | **OpenAI 兼容接口一份代码** | 千问 DashScope / DeepSeek / Ollama 统一 |
| TTS | OpenAI 兼容 `/audio/speech` | 示例默认千问 TTS |
| ASR | OpenAI 兼容 `/audio/transcriptions` | 示例默认 Whisper，按住 LeftAlt 说话 |
| UI | 运行时自建 uGUI（`ChatUI`） | 头顶气泡 + 底部输入栏，免手动搭 Canvas |

**曾讨论但未采用**：Electron + Three.js（迭代快但用户选 Unity）；Unity WebGL 嵌 Electron（性能/透明窗口不可行）。

---

## Git 信息

| 项 | 值 |
|----|-----|
| 仓库 | `https://github.com/1650782309/cursorAgent` |
| 开发分支 | `cursor/unity-desktop-companion-scaffold-dd15` |
| 基线分支 | `main`（目前只有 README，**开发请用功能分支**） |
| PR | #1（草稿） |
| Unity 版本 | **6000.3.20f1** |
| Cloud Agent | https://cursor.com/agents/bc-4303154c-662e-45a0-b2c7-fa458399dd15 |

### 本地拉取

```bash
git clone -b cursor/unity-desktop-companion-scaffold-dd15 https://github.com/1650782309/cursorAgent.git
cd cursorAgent
```

或已有仓库：

```bash
git fetch origin
git checkout cursor/unity-desktop-companion-scaffold-dd15
git pull origin cursor/unity-desktop-companion-scaffold-dd15
```

---

## 架构总览

```
大脑 Brain (Assets/Scripts/Brain, AI)
  PersonaConfig 人设 · MemoryStore(短期原文+长期摘要) · MemorySummarizer
  DialogueManager 对话编排 · EmotionParser 情绪解析
  LLMManager → OpenAICompatibleProvider（千问/DeepSeek/Ollama，流式）
       │ 事件：OnEmotion / OnPartialReply / OnCompleteReply
       ▼
身体 Body (Assets/Scripts/Rendering)
  CharacterManager → ICharacterRenderer
    ├─ SpineCharacterRenderer  (2D, 需 SPINE_UNITY + spine-unity)
    └─ VrmCharacterRenderer    (3D, 需 UNIVRM_PRESENT + UniVRM)
       ▼
语音 Voice (Assets/Scripts/Voice)
  TTS: ITextToSpeech → VoicePlayer → LipSyncDriver(音量→viseme)
  ASR: ISpeechToText ← MicrophoneRecorder ← VoiceInputController(按住说话)
       ▼
界面 UI (Assets/Scripts/UI)
  ChatUI（头顶气泡+输入栏）· ChatDebugUI（IMGUI 备用）
       ▼
窗口 Window (Assets/Scripts/Window)
  DesktopWindowManager · ClickThroughController · CharacterDragHandler
  （需 UNIWINDOW_PRESENT + UniWindowController）
```

**关键抽象**：业务层只依赖 `ICharacterRenderer` 和 `ILLMProvider`，不直接依赖 Spine/VRM/具体模型 API。

---

## 已实现功能

- [x] 角色渲染抽象层 + Spine/VRM 可插拔后端（未装包时占位可编译）
- [x] LLM 流式对话 + `[emotion:xxx]` 情绪标签 → 驱动表情
- [x] 长期记忆：超阈值时 LLM 摘要压缩旧对话，注入 system 上下文
- [x] TTS 语音输出 + 音量驱动 VRM viseme 口型
- [x] ASR 语音输入（按住 LeftAlt 说话 → 转写 → 送入对话）
- [x] ChatUI：运行时自建 uGUI 头顶气泡 + 底部输入栏
- [x] 桌面窗口封装（透明/置顶/穿透/拖动，需 UniWindowController）
- [x] AppBootstrap 装配入口 + 配置模板（StreamingAssets/Config/）

---

## 未完成 / 后续路线

- [ ] **动作状态机**：Mixamo/自制动画 → VRM Animator，`PlayMotion("happy"/"idle")` 驱动全身
- [ ] 多角色 / 形态切换 UI
- [ ] 系统托盘、开机自启、右键菜单
- [ ] 长期记忆升级：sqlite + 向量语义检索
- [ ] 更精细口型：音素/对齐分析（替代当前音量驱动）
- [ ] 美观 UI 预制体（替换运行时自建 Canvas）

---

## 配置与密钥

配置文件在 `Assets/StreamingAssets/Config/`：

| 文件 | 用途 |
|------|------|
| `model_config.json` | LLM 供应商（deepseek/qwen/ollama），改 `active` 切换 |
| `persona.json` | 角色名字、性格、情绪标注规则 |
| `tts_config.json` | 语音合成，`enabled=true` 开启 |
| `asr_config.json` | 语音识别，`enabled=true` 开启 |

**真实 API Key 请放 `*.local.json`**（已在 `.gitignore` 忽略）：
- `model_config.local.json`
- `tts_config.local.json`
- `asr_config.local.json`

---

## 第三方包与编译宏

**未安装第三方包时，工程必须能编译**（占位实现）。安装后再加 Define：

| 包 | 编译宏 | 安装方式 |
|----|--------|---------|
| UniVRM | `UNIVRM_PRESENT` | Package Manager → git URL |
| spine-unity | `SPINE_UNITY` | Esoteric 官网 .unitypackage |
| UniWindowController | `UNIWINDOW_PRESENT` | GitHub kirurobo .unitypackage |

位置：`Edit → Project Settings → Player → Scripting Define Symbols`

⚠️ **常见报错原因**：加了 Define 但没装对应包 → 大量 CS0246 找不到类型。**先清空 Define 或装好包**。

Windows 透明窗口：`Player Settings → 取消 Use DXGI Flip Model Swapchain`。

---

## 场景装配（最小可跑）

1. 新建场景 + Main Camera
2. 空物体 `Character` → 挂 `CharacterManager`
3. 空物体 `App` → 挂 `AppBootstrap`，拖入 Character
4. 空物体 `UI` → 挂 `ChatUI`（或 `ChatDebugUI` 备用）
5. （可选）`VoicePlayer` + `LipSyncDriver` + `MicrophoneRecorder` + `VoiceInputController`
6. （可选）UniWindowController Prefab + `DesktopWindowManager` + `ClickThroughController` + `CharacterDragHandler`

---

## 目录结构

```
Assets/Scripts/
  Core/        Emotion, CharacterAsset, ICharacterRenderer, MainThreadDispatcher
  Rendering/   CharacterManager, SpineCharacterRenderer, VrmCharacterRenderer
  AI/          ChatMessage, LLMConfig, ILLMProvider, OpenAICompatibleProvider, LLMManager, LLMExtensions
  Brain/       PersonaConfig, EmotionParser, MemoryStore, MemorySummarizer, DialogueManager
  Voice/       TTS/ASR 全套 + VoicePlayer, LipSyncDriver, VoiceInputController, WavUtility
  Window/      DesktopWindowManager, ClickThroughController, CharacterDragHandler
  App/         AppBootstrap, PersonaLoader
  UI/          ChatUI, UiFactory, ChatDebugUI
Assets/StreamingAssets/Config/   model_config.json, persona.json, tts_config.json, asr_config.json
```

---

## 命名约定与踩坑

- 角色入口叫 **`CharacterManager`**，不叫 `CharacterController`（避免与 Unity 内置组件冲突）
- `MainThreadDispatcher`：LLM 流式回调在后台线程，更新 UI/角色必须切回主线程
- 情绪协议：模型回复格式 `[emotion:happy]正文...`，`EmotionParser` 解析后驱动表情
- `FindObjectOfType` 在 Unity 6 可能有 obsolete 警告，不影响编译

---

## 给 Agent 的工作指引

1. **先读** `README.md` 和本文件，再读 `Assets/Scripts/` 相关模块
2. **不要**把 AI 逻辑写进渲染后端（Spine/VRM 类里）
3. **不要**在未装第三方包时启用对应 Define
4. **保持** `#if UNIVRM_PRESENT` / `#else` 占位模式，确保零依赖可编译
5. **新功能**优先扩展抽象接口（`ICharacterRenderer` / `ILLMProvider` / `ITextToSpeech` / `ISpeechToText`）
6. **提交**到 `cursor/unity-desktop-companion-scaffold-dd15`，更新本文件中的「已实现/未完成」

---

## 用户环境

- 本地路径：`D:\Work\mico\Git\cursorAgent`
- 操作系统：Windows
- 用户曾遇问题：clone 后在 `main` 分支只有 README → 需切功能分支
