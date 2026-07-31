# 环境搭建（RTX 5090D v2 / 24GB）

5090 系是 Blackwell 架构，计算能力 `sm_120`，比较新。网上大量教程和一键包里的依赖版本
是给 40 系写的，直接照抄会在 5090 上报 `no kernel image is available for execution on the device`。
这一页只讲这些坑，通用安装步骤看 ComfyUI 官方文档。

## 必须注意的依赖

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| PyTorch | cu128 或更高的 wheel | cu121/cu124 的包在 sm_120 上跑不起来 |
| xformers | 不装，或装明确支持 sm_120 的版本 | ComfyUI 现在默认走 PyTorch 原生 SDPA，性能已经够用 |
| SageAttention | 装 2.x 且确认支持 sm_120 | 想提速再装，预编译 wheel 认版本，必要时自己编 |
| bitsandbytes | 支持 Blackwell 的版本 | 训练用 8bit 优化器依赖它，版本不对会静默变慢或直接崩 |
| Triton | 支持 Blackwell 的版本 | 编译型加速与部分量化路径依赖 |

安装 PyTorch：

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

装完先验证，不要等到跑工作流时才发现：

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability())"
# 期望输出类似: 2.x.x+cu128 True (12, 0)
```

`get_device_capability()` 返回 `(12, 0)` 才说明 PyTorch 认得这张卡。

## 精度选择

Blackwell 原生支持 FP8 和 FP4，这一代跑 fp8 量化模型几乎没有质量损失，
所以 Flux 一律用 fp8 底模，24GB 上很舒服。

**训练时用 `bf16`，不要用 `fp16`。** 老教程里的 fp16 在 Blackwell 上更容易出 NaN，
仓库里的训练配置已经统一设成 `mixed_precision = "bf16"`。

## 建议用 Docker

在宿主机上手工装这一套很容易互相打架，尤其是同时要跑推理和训练时。
`orincolor/lora-pilot` 这类镜像把 ComfyUI、Kohya、AI-Toolkit、TensorBoard 打包在一起
并共享模型目录，选明确标注支持 50 系的 tag。

自己搭的话，推理和训练各建一个虚拟环境，不要共用——两边对 bitsandbytes、
transformers 的版本要求经常冲突。

## ComfyUI 启动参数

24GB 显存下的常用组合：

```bash
# 常规使用，让 ComfyUI 自己管显存
python main.py --listen

# 跑 Flux.2 dev 这类超大模型时，主动卸载权重
python main.py --listen --lowvram
```

不要习惯性加 `--lowvram`。24GB 跑 SDXL 和 Flux.1 完全够，加了反而因为反复搬运权重变慢。

## 显存到底够不够

| 任务 | 24GB 上的状态 |
| --- | --- |
| SDXL 出图 | 完全无压力，batch 4-8 |
| Flux.1 dev fp8 出图 | 舒服 |
| Flux.2 klein 出图 | 舒服 |
| Flux.2 dev 出图 | 需要 GGUF Q4/Q5 量化 + 分块加载，能跑但慢 |
| Qwen-Image 出图 | 需要 fp8 或 GGUF 量化 |
| SDXL LoRA 训练 | 宽裕，1024 分辨率 batch 2-4 |
| Flux.1 LoRA 训练 | 够用，需 fp8 底模 + `blocks_to_swap` |
| Flux.2 dev LoRA 训练 | 卡在官方下限，不建议作为主力 |

真正的瓶颈不在单个模型，而在**一条工作流里串了多个大模型**
（例如 Flux + SUPIR + IC-Light）。解法是拆成多个工作流分步跑、中间存 PNG。
这对概念阶段反而更好，每一步的中间产物都留档了。

## 可选的加分项

需要交互式手绘配合时装 [Krita AI Diffusion](https://github.com/Acly/krita-ai-diffusion)，
后端指向同一个 ComfyUI。它是概念探索阶段效率最高的一环：美术在 Krita 里画剪影草稿，
选区实时生成，主导权仍在手上。注意后端要用 SDXL 模型，Flux 太慢不适合交互。
