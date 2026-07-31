# 二次元角色概念设计流水线

面向**角色美术设定探索阶段**的一套可复现工作流：词库、ComfyUI 工作流、批量出图与归档脚本、
以及方向定稿后的角色 LoRA 训练配置。

针对 **RTX 5090D v2 / 24GB 显存** 调过参，二次元角色向。

设计原则只有一条：**概念阶段要的是发散广度和可比较性，不是一致性**。
所以这里所有工具都围绕两件事——用最低成本铺量，以及在铺量之后让方案之间真的可比。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `wildcards/` | 按角色/服装/设计/镜头/画风分类的词库，发散的原料 |
| `prompts/templates/` | 提示词模板：发散、剪影扫描、控制变量比对、Flux 精修、三视图 |
| `workflows/api/` | ComfyUI API 格式工作流，只用核心节点 |
| `scripts/` | 批量出图、出图索引、数据集体检、自测 |
| `training/` | SDXL 与 Flux.1 的角色 LoRA 训练配置 |
| `docs/` | 环境、选型、各阶段操作与取舍说明 |

## 快速开始

```bash
# 1. 不需要 GPU，先确认仓库本身是好的
python scripts/selftest.py

# 2. 看看词库能展开成什么样的提示词（不出图）
python scripts/batch_generate.py --count 5 --dry-run

# 3. 启动 ComfyUI 后，铺 300 张全身发散
python scripts/batch_generate.py --count 300 --label pass1

# 4. 选中方向后，锁姿势扫材质，做严格可比的方案组
python scripts/batch_generate.py \
    --workflow workflows/api/02_pose_locked_compare.json \
    --template prompts/templates/compare_locked.txt \
    --axis outfit/material --fixed-seed 20260731 --label mat-scan

# 5. 给出图建索引，任何一张好图都能查回参数
python scripts/index_outputs.py --root /path/to/ComfyUI/output/pass1
```

出图前把 `workflows/api/*.json` 里的模型文件名改成你本地实际的文件名，
或者用 `--set` 临时覆盖：

```bash
python scripts/batch_generate.py --count 50 \
    --set CHECKPOINT.ckpt_name=noobaiXL_v11.safetensors \
    --set LATENT.width=768 --set LATENT.height=1152
```

## 完整流程

```
发散铺量            控制变量比对         深化精修            结构验证         定稿
SDXL 系      ->    SDXL + ControlNet  ->  Flux.1 dev   ->   放大到 2K   ->  手绘修正
几百张缩略图        同姿势同 seed         img2img 0.5       检查结构        产出设定图
只看剪影            一次只改一维          补材质与结构       是否站得住
                                                                            |
                                                                            v
                                                              需要量产同一角色时才训 LoRA
```

各阶段的具体操作、参数取舍和常见坑，见 `docs/`：

1. [环境搭建](docs/01-environment.md) — Blackwell（RTX 50 系）特有的依赖坑
2. [模型选型](docs/02-models.md) — 二次元底模、ControlNet、放大模型清单
3. [发散与比对](docs/03-divergence.md) — 词库怎么改、网格怎么扫
4. [深化精修](docs/04-refine.md) — 交给 Flux 之后怎么控
5. [角色 LoRA](docs/05-lora.md) — 打标原则与训练参数
6. [评审与归档](docs/06-review-and-assets.md) — 元数据留档、资产管理

## 几个必须先讲清楚的前提

**AI 出图是草稿，不是产出物。** 手部、装备连接结构、纹样对称性、左右一致性基本都有问题，
直接拿去做 3D 会给下游埋坑。定稿产出物应该是一张干净的设定图加结构说明。

**概念阶段不要训 LoRA。** LoRA 会把设计空间锁死在已有方案上，这和发散的目标相反。
等某个方向确定、并且需要产出大量同一角色的图时再训。

**族系一旦选定，训练成本就绑定了。** SDXL 的角色 LoRA 不能用在 Flux 上，反之亦然。
在准备训 LoRA 之前，先确定项目长期用哪一族。

**版权与授权要在立项时确认。** 训练数据来源（尤其是外部委托稿件）、
Flux.1 dev 的非商用许可、真实文化元素的使用，都属于流程之外但必须过的一关。
