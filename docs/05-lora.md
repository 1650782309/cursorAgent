# 角色 LoRA：打标与训练

## 先确认要不要训

**只有满足这两条才训**：某个方向已经定稿；并且需要产出大量同一角色的图
（表情、动作、多套服装、皮肤配色、宣传图）。

概念探索阶段训 LoRA 是本末倒置，会过早锁死设计空间。

另外记住：**族系一旦选定，训练成本就绑定了**。SDXL 的角色 LoRA 不能用在 Flux 上，
反之亦然。二次元项目绝大多数情况选 SDXL 系，因为画风控制和社区生态都在那边。

## 数据集

目录约定：

```
datasets/<角色代号>/images/
    001.png
    001.txt      # 同名标签文件
    002.png
    002.txt
    ...
```

数据量：**20-40 张干净图通常就够**。重要的是覆盖度而不是数量。
必须覆盖正面/侧面/半侧面、全身/半身/脸部特写、不同表情和光照。
全是同一个角度的图，出来的 LoRA 换视角就会崩。

数据质量的破坏力远大于数据不足：抠掉杂乱背景、去掉水印和其他角色、
不要重复喂同一张图、不要把小图放大。

先体检：

```bash
python scripts/prepare_dataset.py --dir datasets/char_xxx/images
```

它会报告缺标签的图、内容完全重复的图、分辨率与长宽比分布、视角覆盖度、
标签词频，以及两类需要你决策的标签。

## 打标原则（比调参重要得多）

一句话：**角色固有特征不入标签，可变要素必须入标签。**

| 类别 | 例子 | 处理 |
| --- | --- | --- |
| 固有特征 | 脸型、发色、瞳色、标志性纹样 | **删掉**，让它们被吸收进触发词 |
| 可变要素 | 姿势、表情、服装、背景、镜头、光照 | **必须打上**，推理时才控制得住 |

反过来打标的后果很具体：

- 把服装打进固有特征（即不标注） → 推理时换不掉衣服
- 把发色留在标签里 → 触发词学不到发色，每次要手写才对
- 不标注姿势 → 换姿势时脸会跟着变，因为模型把姿势和身份绑在了一起

体检脚本会把出现率 ≥85% 的标签列出来，这些基本都是固有特征候选。确认后批量删：

```bash
python scripts/prepare_dataset.py --dir datasets/char_xxx/images \
    --trigger char_xxx_v1 \
    --drop "silver hair,amber eyes,heterochromia" \
    --apply
```

原文件会备份成 `.bak`。

## 触发词

设一个**专属且不与底模已有概念冲突**的词，比如项目代号加编号：`char_ashe01`。
不要用 `ashe`、`knight` 这种常见英文单词——底模里已经有这些概念，会互相污染。

触发词必须在标签第一位，配合 `dataset_*.toml` 里的 `keep_tokens = 1`
保证它不被 `shuffle_caption` 打乱。

## 自动打标

用 WD Tagger 系列批量出初稿（`pythongosssss/ComfyUI-WD14-Tagger`
或独立的 `jhc13/taggui`），阈值设 0.35 左右。

**自动标必须人工过一遍。** 常见问题：把角色固有特征标出来了（要删）、
把不存在的东西标出来了（噪声）、漏掉了关键的可变要素（要补）。
体检脚本里"只出现 1 次"的标签清单就是找噪声用的。

Flux 的打标风格不同：T5 理解自然语言，标签要写成短句而不是 tag 堆叠，
例如 `char_ashe01, a girl in a black lamellar cuirass, standing, front view, grey background`。
同一批图不要混用两种风格。

## 训练

SDXL：

```bash
accelerate launch --num_cpu_threads_per_process 4 sdxl_train_network.py \
    --config_file  training/sdxl_character_lora.toml \
    --dataset_config training/dataset_sdxl.toml
```

Flux.1：

```bash
accelerate launch --num_cpu_threads_per_process 4 flux_train_network.py \
    --config_file  training/flux1_character_lora.toml \
    --dataset_config training/dataset_flux1.toml
```

跑之前把配置里的 `pretrained_model_name_or_path`、`output_name`、
`image_dir` 改成实际值。

### 参数取舍

| 参数 | SDXL | Flux.1 | 为什么 |
| --- | --- | --- | --- |
| `network_dim` | 32 | 16 | 角色任务不需要高 rank，高了只是更容易过拟合 |
| `network_alpha` | 16 | 16 | 一般取 dim 的一半到全量 |
| `learning_rate` | 1e-4 | 8e-5 | 社区验证过的稳定起点 |
| `text_encoder_lr` | 5e-5 | 不训 | TE 学习率高会带偏标签语义；Flux 训 T5 收益小成本高 |
| `train_batch_size` | 2 | 1 | 24GB 上 Flux 只能 1，用梯度累积补到 4 |
| `mixed_precision` | bf16 | bf16 | Blackwell 上不要用 fp16 |
| `min_snr_gamma` | 5 | — | 对二次元线稿类数据有明显收益 |
| `blocks_to_swap` | — | 12 | 24GB 上跑 Flux 的前提，OOM 就加大 |

步数量级：30 张图 × 10 次重复 × 12 epoch ÷ batch 2 ≈ 1800 步，是角色 LoRA 的常用量级。

### 挑 checkpoint，不要用最后一个

配置里 `save_every_n_epochs = 2`，会存下多个中间版本。**最后一个通常是过拟合的。**

过拟合的表现很具体：构图被训练集绑定，换提示词也出同一个姿势和背景；
换服装换不掉；换视角就崩。

`sample_every_n_epochs = 1` 会在训练中途出样图，
`training/sample_prompts.txt` 里的五条提示词就是为了回答三个问题：

1. **换姿势脸还在吗** → 身份是否学到
2. **换服装换得掉吗** → 服装是否被错误地绑进了触发词
3. **构图和背景是否被锁死** → 是否过拟合

一旦样图的背景开始固执地回到训练集的样子，就说明该停了。
先看第 6/8/10 epoch 的对比，挑"像但不过拟合"的那个。

## 推理时的权重

角色 LoRA 一般 0.7-1.0。和画风 LoRA 叠加时：

- 角色 0.7-0.9，画风 0.5-0.8
- 两个都拉满容易互相打架，表现是细节糊化、颜色溢出、脸型被画风拽变形

如果角色权重必须拉到 1.2 以上才像，说明训练不足或数据覆盖度不够，
应该回去补数据重训，而不是靠权重硬顶。

## 版权

训练数据来源要在项目里明确，尤其是外部委托稿件——委托合同里有没有授权用于模型训练
是个真实的法律问题，不是技术问题。这一关在立项时就该过，不要等 LoRA 训完才想起来。
