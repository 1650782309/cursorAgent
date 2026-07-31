# Spine 概念文件（Character Concept）字段说明

`concepts/<id>.yaml` 是 Spine 工作流的输入：它把**角色设定集**里的设定
翻译成骨架和部件能消费的形式。attachment 贴图、骨架、动画、SD 换装 prompt
都由它推导，所以改概念文件就等于改整条流水线的输出。

它**不重复设定集里已有的信息**。配色和头身比只在 `tools/palettes.json`
中维护（见仓库根 README 的「修改配色」），概念文件通过 `bible` 字段引用。

## 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 唯一标识，同时作为产物目录名。只允许 `[a-z0-9_]`。 |
| `bible` | str | 指向设定集里的角色，格式 `<企划>/<角色>`，例如 `kirimicho/akari`。配色与头身比由它带出。 |
| `name` | str | 可选。显示名，默认取设定集里的名字。 |
| `archetype` | str | 角色原型，只用于文档与 prompt。 |
| `summary` | str | 可选。默认取设定集的 `subtitle`（含身高与头身比）。 |
| `canvas` | map | 画布设定，见下。 |
| `aliases` | map | 给设定集的机械配色名起可读的名字，见下。 |
| `palette` | map | 可选。补充设定集里没有的颜色，`{名字: "#RRGGBB"}`。 |
| `rig` | map | 可选。覆盖由头身比推出的骨骼比例，一般不用写。 |
| `parts` | list | 部件列表，见下。这是最核心的字段。 |
| `animations` | list | 要生成的动画名，取值见 `spineforge/animation.py` 的 `GENERATORS`。 |
| `groups` | list[list[str]] | ControlNet 分组。同组部件在控制图里共享 ID，避免接缝处被检出分界线。 |
| `outfits` | map | 换装预设，见下。 |

## `canvas`

| 字段 | 说明 |
| --- | --- |
| `width` / `height` | 渲染视口尺寸（像素）。必须是 `8 * downscale` 的倍数，否则 SD 会自行 padding 导致回写错位。 |
| `origin_x` / `origin_y` | 骨架原点（脚底）在视口中的位置，左上角为 0,0。 |
| `px_per_cm` | 像素/厘米，默认 2.4。设定集给的是厘米身高，靠它换算成画布尺寸——所以 178 cm 的墨在画面上确实比 142 cm 的忍高一头。 |

## 配色与 `aliases`

设定集的配色分组标签是中英混排的（"头发 Hair"、"服装 Costume"），
`spineforge/bible.py` 取其中的英文单词做键，同组按顺序编号：

```
头发 Hair     -> hair, hair_2, hair_3 ...
服装 Costume  -> costume, costume_2, costume_3 ...
```

这些名字机械但稳定。概念文件用 `aliases` 起可读的名字，部件再引用别名：

```yaml
aliases:
  uniform: costume     # 制服
  hanten: costume_3    # 半纏
  crest: costume_5     # 家纹
```

别名写错时报错会列出设定集给的全部键及其用途，照着改即可。

## 骨骼比例

`rig` 由 `bible` 带出的**头身比**推导，长度一律以头长为单位
（`rig.unit` 就是一个头长折合多少像素）：躯干链固定占 3.1 个头长
（头 1.0 + 颈 0.25 + 胸 0.85 + 腰腹 1.0），剩下的全归腿。
所以 5.5 头身的忍和 8.0 头身的伊卡洛斯会得到明显不同的骨架，
改设定集里的头身比，骨架跟着变。

可用的骨骼：`root` `hip` `torso` `chest` `neck` `head`
`upper_arm_l/r` `lower_arm_l/r` `hand_l/r` `thigh_l/r` `shin_l/r` `foot_l/r`
`tail_01` `tail_02` `wing_l/r` `wing_l_02/wing_r_02`。
尾巴和翅膀不是每个角色都有，没挂 attachment 的骨骼是不可见的。

## `parts[]`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 部件名，同时是 slot 名、attachment 名、PNG 文件名。 |
| `bone` | 是 | 绑定的骨骼名，取值见上。 |
| `shape` | 是 | 生成贴图用的形状：`capsule` / `ellipse` / `blade` / `bell` / `plate` / `cape` / `cone` / `wing` / `ring`。 |
| `size` | 是 | `[宽, 高]`，单位是头长。 |
| `offset` | 否 | `[x, y]`，相对骨骼原点的偏移，单位是头长，默认 `[0, 0]`。 |
| `rotation` | 否 | 相对骨骼的旋转角，默认 0。 |
| `mirror` | 否 | 左右翻转贴图。羽翼、耳朵这类对称部件只画一侧，另一侧翻过来用。 |
| `color` | 是 | 引用 `palette` 或 `aliases` 里的颜色名。 |
| `shade` | 否 | 明暗渐变强度 0~1，默认 0.25。 |
| `order` | 是 | 绘制顺序，数值小的先画（在下层）。必须唯一。 |
| `redraw` | 否 | 是否参与 SD 重绘，默认 `true`。脸、瞳孔、唯一的高饱和色这类要锁死的部件设 `false`。 |
| `tags` | 否 | 语义标签列表，用于 outfit 的 `targets` 过滤，例如 `[cloth, upper]`。 |

### 部件坐标系

`offset` 用的是"部件坐标系"：**+Y = 沿骨骼向前**（大腿骨就是向下），
**+X = 面向该方向时的右手边**。这比 Spine 的"局部 +x 沿骨骼"更好写，
转换由 `spineforge/skeleton.py` 统一处理。

### 尺寸可以引用骨骼长度

`size` 与 `offset` 除了写数字，还能引用骨骼长度，避免为每个头身比重算一遍：

```yaml
size:   [0.34, "thigh"]        # 宽 0.34 头长，高等于大腿骨长
offset: [0, "thigh*0.5"]       # 贴图中心落在大腿中点
size:   [0.8, "torso+chest"]   # 盖住腰腹加胸腔
```

## `outfits{}`

| 字段 | 说明 |
| --- | --- |
| `prompt` | SD 正向提示词。描述想要的新衣服。设定集要求画风是 TV 赛璐璐，所以提示词里要带硬边阴影、扁平色块。 |
| `negative_prompt` | SD 负向提示词。除了压低质量与裸露，还要压掉设定集明令禁止的元素（伊卡洛斯的机械翅膀、纯黑、粉色服装等）。 |
| `targets` | 可选。标签列表；只有带这些标签的部件才会被重绘，其余部件强制跳过。留空表示所有 `redraw: true` 的部件。 |
| `palette_hint` | 可选。`{颜色名: "#RRGGBB"}`，只有离线 `mock` 后端会用，SD 后端忽略。 |
| `denoising_strength` | 可选，覆盖全局重绘强度。 |

`mock` 后端把 `palette_hint` 的色值**按书写顺序**铺成一条从画面顶部到底部的
渐变（上装在上、下装在下，照高度铺就能得到分层合理的衣服）。
所以写 hint 时按"从上到下"排列，别把只占一小块的点缀色塞进中间。
