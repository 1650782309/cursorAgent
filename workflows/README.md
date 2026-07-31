# 工作流说明

## 两份格式，各管一件事

| 目录 | 格式 | 用途 |
| --- | --- | --- |
| `workflows/api/` | API 格式 | 给 `scripts/batch_generate.py` 批量驱动，**这是真实来源** |
| `workflows/ui/` | UI 格式 | 在浏览器里打开、手动调参和交互式操作 |

`workflows/ui/` 由脚本从 `workflows/api/` 生成，不要手改：

```bash
# ComfyUI 需要先启动
python scripts/api_to_ui_workflow.py
```

转换时会连上本机 ComfyUI 读取真实的节点定义（`/object_info`），据此判断哪些参数是控件、
哪些是连线接口，所以不会出现"照文档写死参数顺序、换个 ComfyUI 版本就错位"的问题。
换了 ComfyUI 版本或装了新节点包之后，重跑一次即可。

在浏览器里用 **工作流 → 打开** 选择 `workflows/ui/*.json` 载入。

> ComfyUI 首次打开时会加载它自带的示例工作流，那个示例引用了本仓库没有下载的模型
> （比如 `anything-v5-PrtRE.safetensors`），因此会报"缺失模型"。这与本仓库无关，
> 载入上面的工作流即可，或者把示例里的 checkpoint 换成 `illustriousXL.safetensors`。

## 为什么以 API 格式为准

`workflows/api/*.json` 是 ComfyUI 的 **API 格式**（`{节点ID: {class_type, inputs}}`），
不是界面里"保存"出来的 UI 格式。原因：

- API 格式是脚本注入参数的直接目标，`scripts/batch_generate.py` 靠它工作
- 结构扁平，diff 清晰，参数改动在代码评审里看得懂
- 没有画布坐标等噪声，不会因为拖动节点产生无意义的改动

这些文件用于**脚本化批量执行**。交互式操作（局部重绘、逐块推进）在界面里做，
载入 `workflows/ui/` 下对应的那一份即可。改了参数想固化回来，就改 `workflows/api/`
再重新生成 UI 版，不要反过来——否则两边会各改各的。

## 只用核心节点

四条工作流刻意只用 ComfyUI 自带节点，装完 ComfyUI 就能跑。
这是为了避免自定义节点升级导致参数名漂移——那类故障排查起来非常费时间，
而概念阶段的工作流本身并不复杂，不值得为此引入依赖。

需要 IP-Adapter、Impact-Pack、UltimateSDUpscale 这类扩展时，
在界面里搭好、导出 API 格式（开发者模式下的 "Save (API Format)"）放进这个目录即可，
只要保留下面的标记约定，脚本就能直接驱动。

## 标记约定

脚本通过节点的 `_meta.title` 找到要注入的节点。自己搭工作流时，
把节点标题改成对应名字（界面里右键节点 → Title）：

| 标题 | 节点类型 | 脚本会写入 |
| --- | --- | --- |
| `POSITIVE` | CLIPTextEncode | `inputs.text` ← 展开后的提示词（必需） |
| `NEGATIVE` | CLIPTextEncode | `inputs.text` ← 负面提示词（可选） |
| `SAMPLER` | KSampler 等 | `inputs.seed` ← 本次 seed（必需） |
| `SAVE` | SaveImage | `inputs.filename_prefix` ← `<label>/<轴取值>/img` |

其余节点用 `--set TITLE.input=value` 覆盖，例如：

```bash
--set CHECKPOINT.ckpt_name=noobaiXL_v11.safetensors
--set LATENT.width=768
--set SAMPLER.steps=16
--set INPUT_IMAGE.image=selected_01.png
--set CONTROLNET_APPLY.strength=0.7
```

值会先按 JSON 解析，所以数字、布尔、字符串都能正确传入。

## 四条工作流

### `01_divergence_sdxl.json` — 发散铺量

SDXL txt2img，CLIP skip -2，`euler_ancestral` 20 步。
ancestral 采样器是故意选的：随机性更大，同一提示词的变化更多，适合撞方向。

主要节点标记：`CHECKPOINT`、`CLIP_SKIP`、`POSITIVE`、`NEGATIVE`、`LATENT`、`SAMPLER`、`SAVE`

### `02_pose_locked_compare.json` — 锁姿势比对

在 01 的基础上加 ControlNet。控制图要先放进 ComfyUI 的 `input/` 目录，
用 `--set CONTROL_IMAGE.image=xxx.png` 指定。

`CONTROLNET_APPLY.strength` 默认 0.85、`end_percent` 0.75：
前 75% 的步数锁结构，后 25% 放开让模型收细节。姿势跑偏就调高 strength，
装备细节被压得太死就调低 end_percent。

控制图的三种来源见 [docs/03-divergence.md](../docs/03-divergence.md#锁姿势)。

### `03_refine_flux_img2img.json` — Flux 深化

Flux.1 dev fp8 的 img2img。注意几点：

- CFG 固定 1.0，画面强度靠 `GUIDANCE.guidance` 调（二次元向 3.0-3.5）
- 负面条件走 `ConditioningZeroOut` 置空，跑脚本时要加 `--negative none`
- `UNET.weight_dtype` 设 `fp8_e4m3fn`，Blackwell 原生支持，几乎无质量损失
- 需要 `clip_l`、`t5xxl_fp8_e4m3fn`、`ae.safetensors` 三件套

### `04_upscale_check.json` — 放大验证结构

放大模型放到 4 倍 → 降回 2 倍 → `denoise 0.35` 二次采样重建细节。
用途是检查结构逻辑是否成立（关节穿模、装备能不能穿脱、纹样对不对称），
不是为了出成品。

二次元一定要用保线条的放大模型（`4x-AnimeSharp` 之类），
通用放大模型会糊线条、给平涂区域加上不该有的噪点。

## 改动后

```bash
python scripts/selftest.py                  # 不需要 ComfyUI，校验结构
python scripts/api_to_ui_workflow.py        # 需要 ComfyUI，重新生成界面版
```

`selftest.py` 会校验每个工作流的节点引用是否合法、必需标记是否齐全。
注意它**不校验节点参数名是否被 ComfyUI 接受**——那需要真的连上 ComfyUI，
所以换过自定义节点版本后，先用 `--count 1` 跑一张确认。

`api_to_ui_workflow.py` 因为要读真实节点定义，顺带就能发现"本机缺少某个节点包"
和"参数名对不上"这两类问题，改完工作流后建议一并跑一遍。
