# 评审与资产管理

概念阶段最常见的事故不是出不了好图，而是：**上周那张图特别好，但再也生成不出来了。**
这一页讲怎么避免。

## 三层留档

| 层 | 内容 | 位置 |
| --- | --- | --- |
| 批次级 | 模型、模板、词库随机种子、扫描轴、节点覆盖 | `runs/<时间戳>-<label>/run.json` |
| 单图级 | seed、完整提示词、各维度实际抽到的条目 | `runs/.../manifest.jsonl` |
| 图片内嵌 | 完整 API 工作流 | PNG 的 tEXt 文本块，ComfyUI 自动写入 |

三层是冗余的，故意如此。PNG 元数据最可靠（跟着文件走），
manifest 最好查（能看到是哪个词条撞出来的），run.json 用来复现整批。

**不要用会剥离元数据的工具处理图片。** 很多图片压缩工具、聊天软件、
某些图库软件的导出功能会把 PNG 文本块删掉，那张图就废了。评审时传缩略图，
原图留在本地。

## 建索引

```bash
# 扫描出图目录，产出 index.jsonl 和 index.csv
python scripts/index_outputs.py --root /path/to/ComfyUI/output/pass1
```

`index.csv` 用 Excel 直接打开（已按 UTF-8 BOM 编码，不会乱码），
按 seed、底模、提示词排序筛选。

按字段过滤：

```bash
# 找出某个 seed 的所有图
python scripts/index_outputs.py --root output/pass1 --filter seed=1541804686

# 找出提示词里带某个词条的图
python scripts/index_outputs.py --root output/pass1 --filter positive="lamellar"
```

按字段分组建软链接，方便并排评审：

```bash
python scripts/index_outputs.py --root output/pass1 \
    --group-by checkpoint --link-dir review/by-model
```

## 图库工具

出图量会到几千张，光靠文件管理器不够。开源可选：

- **`RupertAvery/DiffusionToolkit`** — 本地图库，能读 PNG 生成元数据并做检索，
  开源，可替代 Eagle。这是目前最顺手的选择。
- **`zanllp/sd-webui-infinite-image-browsing`** — 也能独立跑，浏览加元数据检索。

**评审时按方向浏览，不要按时间浏览。** 时间顺序会让你陷入"最近出的图"偏好，
按方向（也就是按扫描轴的子目录）看才能公平比较。

## 目录约定

```
runs/                      批次元数据（脚本自动生成，不入库）
output/                    ComfyUI 出图（不入库）
    pass1/                     发散第一轮
    mat-scan/                  材质扫描
        blackened-steel.../        按扫描轴取值自动分目录
review/                    评审用的软链接树与选中稿
datasets/                  LoRA 训练数据（不入库，用 git-lfs 或 DVC 单独管）
models/                    模型文件（不入库）
```

`.gitignore` 已经把这些排除了。**进 git 的只有词库、模板、工作流、脚本、配置和文档**——
也就是"生产资料"，而不是"产物"。

## 什么该进版本管理

| 类型 | 进 git | 说明 |
| --- | --- | --- |
| 词库 `wildcards/` | 是 | 项目的美术资产，每轮迭代都该提交 |
| 模板 `prompts/` | 是 | 质量前缀、维度组合的演进过程有价值 |
| 工作流 `workflows/` | 是 | JSON 可 diff，这是选 ComfyUI 而不是 WebUI 的主要原因 |
| 训练配置 `training/` | 是 | 参数与结果的对应关系要能查 |
| 模型 checkpoint | 否 | 太大，用共享目录或模型管理工具 |
| 训练数据集 | 否 | 用 git-lfs 或 DVC 单独管，并留意版权 |
| 出图 | 否 | 选中的定稿图可以单独放 `review/` 并用 git-lfs |
| 训出的 LoRA | 否 | 但要记录它对应哪个数据集版本和哪份 config |

多人协作时，`ComfyUI-Manager` 的节点快照也建议提交，
否则换台机器很可能打不开同一个工作流。

## 团队协作

- **工作流版本化**：改动工作流走正常的 PR 流程，改了什么参数、为什么改，
  在 commit message 里写清楚。这比在群里发截图有用得多。
- **词库归属**：词库按世界观分类维护，谁负责哪个模块的设计就负责对应词库。
  词库的演进本身就是项目美术风格收敛的记录。
- **共享一台 GPU 机**：`orincolor/lora-pilot` 这类 Docker 镜像把推理和训练环境
  打包在一起并共享模型目录，比每人一套环境省事。

## 改动后的验证

改过词库、模板、工作流或脚本之后：

```bash
python scripts/selftest.py
```

不需要 GPU、不需要 ComfyUI、不需要第三方库，几秒钟跑完。
它会检查词库有无重复条目、模板引用的词库是否都存在、
工作流的节点引用是否合法、PNG 元数据解析是否正确，
并用桩服务器跑一遍完整的提交—轮询—下载流程。
