# 角色概念（Character Concept）字段说明

概念文件是整套工作流的唯一输入。一个 `concepts/<id>.yaml` 描述一个角色：
它的体型比例、部件（attachment）拆分、配色、绑定到哪根骨骼、以及可用的换装（outfit）预设。

下游所有产物——attachment 贴图、Spine 骨架、动画、SD 重绘 prompt——都由它推导出来，
所以改概念文件就等于改整条流水线的输出。

## 顶层字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 角色唯一标识，同时作为产物目录名。只允许 `[a-z0-9_]`。 |
| `name` | str | 角色显示名。 |
| `archetype` | str | 角色原型（mage / knight / ranger…），只用于 prompt 与文档。 |
| `summary` | str | 一句话设定，只用于文档与 `spineforge show`。 |
| `canvas` | map | 画布设定，见下。 |
| `palette` | map | 命名颜色表，`{名字: "#RRGGBB"}`。部件用名字引用颜色。 |
| `rig` | map | 骨骼比例参数，见下。 |
| `parts` | list | 部件列表，见下。这是最核心的字段。 |
| `animations` | list | 要自动生成的动画名，取值见 `spineforge/animation.py` 的 `GENERATORS`。 |
| `groups` | list[list[str]] | ControlNet 分组。同组部件在 ctrl 图里共享同一个 ID，避免接缝处被 canny 画出分界线。 |
| `outfits` | map | 换装预设，`{预设名: {prompt, negative_prompt, ...}}`，见下。 |

## `canvas`

| 字段 | 说明 |
| --- | --- |
| `width` / `height` | 渲染视口尺寸（像素）。会被自动对齐到 `8 * downscale` 的倍数。 |
| `origin_x` / `origin_y` | 骨架原点在视口中的位置（像素，左上角为 0,0）。 |

## `rig`

`unit` 是全局缩放（像素/单位），其余是各段骨骼长度（单位制）。
`spineforge/skeleton.py` 用它们摆出 T-pose 骨架。

## `parts[]`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 部件名，同时是 slot 名、attachment 名、PNG 文件名。 |
| `bone` | 是 | 绑定的骨骼名，取值见 `skeleton.py` 的 `BONE_LAYOUT`。 |
| `shape` | 是 | 生成贴图用的形状：`capsule` / `ellipse` / `blade` / `bell` / `plate` / `cape`。 |
| `size` | 是 | `[宽, 高]`，单位是骨骼单位（会乘 `rig.unit`）。 |
| `offset` | 否 | `[x, y]`，相对骨骼原点的偏移，默认 `[0, 0]`。 |
| `rotation` | 否 | 相对骨骼的旋转角，默认 0。 |
| `color` | 是 | 引用 `palette` 里的颜色名。 |
| `shade` | 否 | 明暗渐变强度 0~1，默认 0.25。 |
| `order` | 是 | 绘制顺序，数值小的先画（在下层）。 |
| `redraw` | 否 | 是否参与 SD 重绘，默认 `true`。脸、瞳孔这类要保形的部件设 `false`。 |
| `tags` | 否 | 语义标签列表，用于 outfit 的 `targets` 过滤，例如 `[cloth, upper]`。 |

## `outfits{}`

| 字段 | 说明 |
| --- | --- |
| `prompt` | SD 正向提示词。描述"想要的新衣服"。 |
| `negative_prompt` | SD 负向提示词。通常要压掉裸露、低质量。 |
| `targets` | 可选。标签列表；只有带这些标签的部件才会被重绘，其余部件强制跳过。留空表示所有 `redraw: true` 的部件。 |
| `palette_hint` | 可选。`{颜色名: "#RRGGBB"}`，离线 mock 后端用它做确定性配色替换，SD 后端忽略。 |
| `denoising_strength` | 可选，覆盖全局重绘强度。 |
