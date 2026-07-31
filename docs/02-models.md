# 模型选型（二次元角色向）

## 底模分工

24GB 显存下性价比最高的组合是**两族并用**：SDXL 系负责发散，Flux.1 负责深化。

| 阶段 | 族系 | 原因 |
| --- | --- | --- |
| 发散铺量 | SDXL 系 | 快、显存便宜、风格跨度大，撞出意外组合的概率高 |
| 控制变量比对 | SDXL 系 | ControlNet 生态最成熟，姿势/深度控制最可靠 |
| 深化精修 | Flux.1 dev | 语义理解强、结构和解剖更稳，经得起放大 |
| 中文提示词 / 画面内中文 | Qwen-Image 系 | 这是它的强项，Flux 做不到 |

不要在比对阶段换族系。同一组方案必须用同一个底模出，否则你比的是模型差异而不是设计差异。

## 二次元 SDXL 精调

选择时看三点：画风是否接近项目定位、标签体系、社区 LoRA 数量。

| 类型 | 代表 | 标签体系 | 说明 |
| --- | --- | --- | --- |
| Illustrious / NoobAI 系 | `illustriousXL`、`noobaiXL` | danbooru tag | 目前二次元向的主流，标签响应准，配套 LoRA 多 |
| Pony 系 | `ponyDiffusionV6XL` 及其精调 | danbooru tag + score 前缀 | 需要 `score_9, score_8_up, score_7_up` 质量前缀 |
| 通用写实向 | `juggernautXL` 等 | 自然语言偏多 | 二次元项目一般不用，做材质参考时偶尔有用 |

**质量前缀要跟着底模换。** 仓库模板默认写的是 Illustrious 系：

```
masterpiece, best quality, very aesthetic, absurdres
```

换 Pony 系时把 `prompts/templates/*.txt` 开头替换为：

```
score_9, score_8_up, score_7_up
```

**不要用过拟合的融合模型做概念发散。** 有些融合模型会把所有设计都拽回同一张脸、
同一种构图，这在量产阶段是优点，在探索阶段是灾难。判断方法：固定提示词只换 seed 出 20 张，
如果脸和构图高度雷同，就不适合做发散。

**CLIP skip 设 -2。** 二次元 SDXL 精调基本都是按 CLIP skip 2 训的，
仓库工作流里已经放了 `CLIPSetLastLayer` 节点。注意这是**推理**设置，
SDXL **训练**时不使用 clip_skip，训练配置里不要加。

## 采样参数起点

| 用途 | 采样器 | 调度器 | 步数 | CFG |
| --- | --- | --- | --- | --- |
| 发散铺量 | `euler_ancestral` | `normal` | 20 | 5.0 |
| 定稿出图 | `dpmpp_2m` | `karras` | 26-30 | 5.0-6.5 |
| 放大二次采样 | `dpmpp_2m` | `karras` | 20 | 4.5 |
| Flux.1 | `euler` | `simple` | 25 | 1.0（改 FluxGuidance 3.0-3.5） |

发散阶段用 ancestral 采样器是故意的：它引入的随机性更大，同一提示词的变化更多，
适合"撞方向"。定稿阶段换成收敛型采样器保证稳定。

Flux 的 CFG 必须是 1.0，画面强度靠 `FluxGuidance` 节点的 `guidance` 调，
二次元向建议 3.0-3.5，调到 4 以上会明显变"油"。

## 分辨率

SDXL 只在训练桶附近表现正常，全身角色用：

- `832 x 1216` — 全身标准，默认值
- `896 x 1152` — 半身与略竖
- `1024 x 1024` — 脸部特写
- `640 x 960` — 发散阶段抢速度用，缩略图评审够了

不要用 `512 x 768`，SDXL 在这个尺寸下构图会崩。

## 配套模型

| 类型 | 建议 | 用途 |
| --- | --- | --- |
| ControlNet OpenPose (SDXL) | 官方或社区 SDXL openpose 权重 | 锁姿势做可比方案组 |
| ControlNet Depth (SDXL) | 同上 | Blender 简模渲深度图，做三视图 |
| ControlNet Lineart / Canny (SDXL) | 同上 | 接手绘草稿 |
| 放大模型 | `4x-AnimeSharp`、`4x_NMKD-Siax` | 二次元线稿放大，前者更锐 |
| Flux.1 配套 | `clip_l`、`t5xxl_fp8_e4m3fn`、`ae.safetensors` | Flux 工作流的三件套 |
| IP-Adapter (SDXL) | `ip-adapter-plus_sdxl`、style 变体 | moodboard 风格注入 |

放大模型选择对二次元影响很大：`4x-AnimeSharp` 保线条，通用放大模型会把线条糊掉、
把平涂区域加上不该有的噪点纹理。

## 必要的自定义节点

仓库自带的工作流**只用 ComfyUI 核心节点**，装完 ComfyUI 就能跑，
这是为了避免自定义节点版本更新导致参数名漂移。

以下是推荐但非必需的扩展，用途和替代方案：

| 节点包 | 用途 | 不装的话 |
| --- | --- | --- |
| `ComfyUI-Manager` | 依赖管理、节点快照 | 手工装，换机器容易打不开工作流 |
| `comfyui_controlnet_aux` | OpenPose/Depth 等预处理器 | 用 Blender 或姿势编辑器预先渲好控制图，走 `LoadImage` |
| `ComfyUI_IPAdapter_plus` | moodboard 风格参考 | 用 img2img 低重绘代替 |
| `ComfyUI-Impact-Pack` | 自动检测脸/手并分区精修 | 手动框选 inpaint |
| `ComfyUI_UltimateSDUpscale` | 真正的分块放大 | 用仓库的 `04_upscale_check.json`（核心节点版） |
| `ComfyUI-GGUF` | 加载 GGUF 量化大模型 | 跑不了 Flux.2 dev 这一档 |

不建议接入的：各种"角色生成一体化"节点包（本质是提示词拼装器，
会把设计空间限制在别人预设的 tag 库里）。这个仓库的 `wildcards/` 就是为了让词库
留在你自己手里、进 git、按项目世界观演进。
