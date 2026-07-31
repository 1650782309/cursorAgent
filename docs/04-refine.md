# 深化精修

方向筛到 3-5 个之后进入这一阶段。目标从"找方向"变成"把方向做成站得住的设计"。

## 交给 Flux 补结构和材质

SDXL 阶段选中的图，用 Flux.1 dev 做 img2img 低重绘。这是 24GB 上最划算的一步：
Flux 的结构和解剖比 SDXL 稳得多，语义理解也强，能听懂"肩甲是氧化铜配黑色皮革绑带"这类描述。

1. 把选中的图放进 ComfyUI 的 `input/` 目录
2. 编辑 `prompts/templates/refine_flux.txt`，把方括号里的占位替换成实际定稿描述
3. 跑：

```bash
python scripts/batch_generate.py \
    --workflow workflows/api/03_refine_flux_img2img.json \
    --template prompts/templates/refine_flux.txt \
    --negative none \
    --count 6 --label refine-v1 \
    --set INPUT_IMAGE.image=selected_01.png
```

`--negative none` 是必须的：Flux 走 CFG=1，工作流里用 `ConditioningZeroOut`
把负面条件置空，塞负面提示词没有意义。

### 重绘强度怎么选

| denoise | 效果 | 用途 |
| --- | --- | --- |
| 0.30-0.40 | 只改材质和细节，构图完全保留 | 已经满意，只想提质量 |
| 0.45-0.55 | 保留构图与大形，重画材质与结构细节 | 默认档，最常用 |
| 0.60-0.70 | 大形保留，设计细节会被重新解释 | 想让 Flux 提新方案 |
| >0.75 | 基本等于重画 | 不如直接 txt2img |

```bash
--set SAMPLER.denoise=0.45
```

一次跑 6 张不同 seed，挑一张继续，比反复调参更快。

### Flux 的画风问题

Flux 默认有明显的"偏摄影感、偏平滑"倾向，二次元项目要在提示词里明确压住：
模板末尾的 `Clean lineart with flat cel shading, crisp material separation`
就是干这个的。如果还是偏写实，两个办法：

- 把 denoise 降到 0.4 以下，让 SDXL 的画风主导
- 用二次元向的 Flux LoRA（社区有，但数量远少于 SDXL）

如果画风始终压不住，就不要在这一步用 Flux，改用 SDXL 自己做 hires 二次采样。
`04_upscale_check.json` 本身就能当这个用。

## 局部重绘迭代

脸、头饰、武器、鞋子分区域推进，**不要整图重抽**——那会破坏已经定下来的部分。

这一步交互性强，建议在 ComfyUI 界面或 Krita AI Diffusion 里手动做，
脚本化没有意义。核心原则：

- 一次只改一个区域，改完确认再动下一处
- 遮罩边缘留出足够的过渡区，否则接缝明显
- 局部重绘的提示词只描述那个区域，不要复制整张图的提示词

需要自动化处理脸和手时装 `ComfyUI-Impact-Pack`，它能自动检测并分区精修。

## 结构验证：放大到 2K

**这是概念评审必须过的一关。** 很多方案在缩略图阶段很惊艳，放大后会发现结构逻辑不成立：
关节穿模、装备无法穿脱、承重不合理、纹样左右不对称、绑带没有起点终点。

```bash
python scripts/batch_generate.py \
    --workflow workflows/api/04_upscale_check.json \
    --template prompts/templates/refine_flux.txt \
    --count 1 --label upscale-check \
    --set INPUT_IMAGE.image=refine_v1_final.png \
    --set UPSCALE_MODEL.model_name=4x-AnimeSharp.pth
```

工作流的做法是：放大模型放到 4 倍，再降回 2 倍，然后用 `denoise 0.35`
的二次采样把细节重建。只用核心节点，装完 ComfyUI 就能跑。

需要更高质量的真正分块放大，装 `ComfyUI_UltimateSDUpscale`；
`SUPIR` 在 24GB 上也能跑，把分块尺寸调小一点。

放大后要人工检查的清单：

- 手指数量与关节朝向
- 装备与身体的连接方式（绑带、卡扣、铰链有没有实际结构）
- 左右对称元素是否真的对称
- 布料的褶皱走向是否符合重力和受力
- 纹样在转折面上是否连续

这些几乎不可能靠出图解决，是定稿前手绘修正的工作清单。

## 氛围比稿

方案定了之后，用重打光出宣传图向的比稿。装 `IC-Light`（SDXL 侧），
同一设计换光照氛围，评审时看这个设计在不同场景下是否都立得住。

也可以简单点：把 `wildcards/shot/lighting.txt` 设为扫描轴。

```bash
python scripts/batch_generate.py \
    --axis shot/lighting --fixed-seed 20260731 --label mood \
    --template prompts/templates/compare_locked.txt
```

注意这只是提示词层面的换光，不如 IC-Light 精确，但足够做方向判断。

## 一个流程提醒

不要把 Flux、放大、重打光串在一条超长工作流里。24GB 显存下多个大模型同时加载
是真正的瓶颈。**拆成多个工作流分步跑、中间存 PNG**，这样每一步的中间产物都留档，
出问题也能定位到具体哪一步。
