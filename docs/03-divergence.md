# 发散与控制变量比对

概念探索最核心的两步。目标不是出好图，是**尽快摸清设计空间的边界**，
然后**在候选之间做出可信的比较**。

## 第一步：发散铺量

低成本、高数量、只看剪影和第一眼记忆点。

```bash
python scripts/batch_generate.py --count 300 --label pass1
```

发散阶段的成本控制：

```bash
# 抢速度：小分辨率 + 少步数，缩略图评审足够
python scripts/batch_generate.py --count 500 --label pass1-fast \
    --set LATENT.width=640 --set LATENT.height=960 \
    --set SAMPLER.steps=16
```

一张图压到几秒，一晚上能出几千张。**评审时把图缩到 100px 看**，
能在缩略图里认出来的方案才有资格进下一轮。

### 只比剪影

抛开配色和材质的干扰：

```bash
python scripts/batch_generate.py --count 200 --label silhouette \
    --template prompts/templates/divergence_silhouette.txt
```

### 关于"不合理"的随机组合

你会看到 `1boy` 配 `nun habit`、`clockwork tinkerer` 配 `qipao` 这类组合。
这不是 bug，是发散的目的——人写提示词会不自觉收敛到自己的舒适区，
只有随机抽取才会撞出你想不到的方向。大部分是废的，但十分之一有价值就够了。

如果某几维确实必须固定，用 `--axis` 把它钉住（见下），或者直接改模板里的对应行。

## 第二步：控制变量比对

发散完你会发现方案没法比——每张图姿势光照都不一样，看着好可能只是构图好。
解决办法是**锁死无关变量，一次只改一维**。

### 网格模式

```bash
# 扫材质：材质穷举，其余随机，但采样 seed 固定
python scripts/batch_generate.py \
    --template prompts/templates/compare_locked.txt \
    --axis outfit/material \
    --fixed-seed 20260731 --label mat-scan
```

`--fixed-seed` 是关键。它让所有方案共享同一份初始噪声，
构图和姿势会高度一致，差异几乎只来自你扫的那一维。

两维交叉：

```bash
# 剪影 × 配色，15 × 20 = 300 格
python scripts/batch_generate.py \
    --axis design/silhouette --axis design/color_scheme \
    --fixed-seed 20260731 --limit 300 --label sil-x-color
```

每格多出几张降低偶然性：

```bash
python scripts/batch_generate.py --axis outfit/material --repeat 3 \
    --fixed-seed 20260731 --label mat-scan-x3
```

出图会按扫描轴的取值自动分到子目录，例如
`mat-scan/blackened-steel-with-oil-sheen/`，并排评审时直接按目录看。

### 锁姿势

固定 seed 只能让构图接近，要真正锁死姿势得上 ControlNet：

```bash
python scripts/batch_generate.py \
    --workflow workflows/api/02_pose_locked_compare.json \
    --template prompts/templates/compare_locked.txt \
    --axis outfit/style --fixed-seed 20260731 --label style-scan \
    --set CONTROL_IMAGE.image=tpose_ref.png
```

控制图（`CONTROL_IMAGE.image`）需要先放进 ComfyUI 的 `input/` 目录。三种来源：

1. **Blender 简模**：摆一个标准站姿的比例参考（哪怕几个基本几何体拼的），
   渲 depth 或 normal 图。最可靠，也能顺便解决三视图。
2. **姿势编辑器**：`sd-webui-3d-open-pose-editor` 之类，导出 openpose 骨架图。
3. **现成图预处理**：装 `comfyui_controlnet_aux`，用 `OpenposePreprocessor`
   从参考图提骨架。

`CONTROLNET_APPLY.strength` 默认 0.85、`end_percent` 0.75，
意思是前 75% 的步数锁结构、后 25% 放开让模型自己收细节。
姿势跑偏就调高 strength，装备细节被压得太死就调低 end_percent。

## 词库怎么改

`wildcards/` 下每个 `.txt` 一行一个条目，`#` 开头是注释。
改词库是这套流程里回报最高的动作——**通用词库撞出来的东西都很泛，
按项目世界观维护的词库才有效**。

建议的推进方式：

1. 先用自带词库跑一轮发散，把出图过一遍
2. 把明显不属于本项目的条目删掉（比如世界观里没有枪械就清掉火器）
3. 把评审时觉得"有意思"的方向拆成词条补进去
4. 每轮迭代都提交到 git，词库本身就是项目的美术资产

维度数量的经验值：**8-14 个维度**。少于 8 个方案区分度不够，
多于 14 个提示词会过载，SDXL 会开始忽略后面的标签。
`divergence_fullbody.txt` 目前是 14 维，接近上限。想加维度就先删一个。

`design/motif.txt`（标志性符号）默认没进主模板，就是因为维度预算已经用满。
它更适合在收敛阶段单独扫。

## 模板语法

```
__path/name__     从 wildcards/path/name.txt 随机抽一行
{a|b|c}           从若干候选中随机抽一个
{2$$a|b|c}        抽 2 个，用 ", " 连接
# 开头            注释
```

词库条目本身也可以包含上述语法，会递归展开（最多 12 层）。

改完模板或词库先 dry-run 看结果，别直接开跑几百张：

```bash
python scripts/batch_generate.py --count 5 --dry-run
```

## 复现

每个批次会在 `runs/<时间戳>-<label>/` 下留两个文件：

- `run.json` — 本批次的模型、模板、词库随机种子、扫描轴、节点覆盖
- `manifest.jsonl` — 每张图的 seed、完整提示词、各维度实际抽到的条目、输出文件名

想复现整批，用 `run.json` 里的 `wildcard_seed` 传给 `--seed`；
想复现单张，从 `manifest.jsonl` 里取那一行的 `prompt` 和 `seed`。
