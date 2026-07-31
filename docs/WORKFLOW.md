# 工作流手册

面向要真正用这套流程出图的人：算法怎么对应到 RedrawSpine、参数怎么调、
出了瑕疵往哪查、以及接入现有 Spine 工程还差什么。

## 与 RedrawSpine 的对应关系

| RedrawSpine | 本仓库 | 差异 |
| --- | --- | --- |
| `spine2restposepsd.py` + Spine 命令行导出 | `spineforge/skeleton.py`、`spineforge/partgen.py` | 骨架和贴图直接由概念生成，不再需要 Spine 编辑器导出 PSD |
| Photoshop 标记重绘 / 不重绘图层 | 概念里的 `redraw` 字段与 outfit 的 `targets` | 不需要 Photoshop，也不需要对比两次导出的 json |
| `preproccess.py` + analyzer 的 keypose 搜索 | `spineforge/keypose.py` | 算法一致：贪心选"新露出纹素最多"的帧 |
| `uv_redraw.glsl` | `raster.render_uv` | 同样编码成 `(部件ID << 24) \| 纹素下标`；阈值 0.05 / 0.55 原样保留 |
| `ctrl.glsl` + WebUI 的 canny 预处理器 | `raster.render_ctrl` + `raster.edges_from_ids` | 直接从分组 ID 图求边界，不跑 canny。ID 图是分片常量的，边界更干净，也不会在渐变里误检 |
| `rgb.glsl` | `raster.render_color` | numpy alpha 混合 |
| analyzer `-frame` 的回写 | `spineforge/writeback.py` | 边缘剔除的 HSV 判据、梯度阈值 3000、5x5 邻域投票都照搬 |
| `floodWhitePixelWithNeighborColor`（CUDA） | `writeback.flood_unwritten` | numpy 迭代膨胀 |
| `UVmapping.py` | `spineforge/pipeline.py` | 多了离线 mock 后端和覆盖率报告 |

两处有意的改动：

**ControlNet 输入不走 canny。** 原实现把分组 ID 图渲染成灰度再跑 canny 检边。
ID 图本来就是分片常量的，直接比较相邻像素的 ID 就能得到精确边界，
省掉一次 WebUI 往返，也避免 canny 在灰度渐变里检出多余的线。

**部件 ID 从 1 开始。** 原实现的绘制列表从 0 开始编号，
0 号部件的 0 号纹素编码出来是 0，和"空像素"撞了。这里把 0 留给空和遮挡体。

## 参数调优

### 覆盖率上不去

`preprocess` 报告里某个部件覆盖率低，说明现有动画就没怎么展示它。按顺序试：

1. 调小 `SPINEFORGE_KEYPOSE_SAMPLE_STEP`（默认 0.1 秒），采样更密可能找到更好的帧。
2. 调大 `SPINEFORGE_KEYPOSE_MAX_COUNT`（默认 8）。注意每多一个姿势就多一次 SD 推理。
3. 调小 `SPINEFORGE_KEYPOSE_MIN_GAIN`（默认 512）让迭代继续下去。
4. 以上都不行就是动画本身的问题——给概念加一段专门展示该部位的动画。

剩下没覆盖到的纹素会靠邻域扩散填色。扩散出来的颜色不准，但至少和周围连得上；
如果这块区域在游戏里会被转出来，就必须靠补动画解决，不能指望扩散。

### 贴图边缘有脏边

调大 `SPINEFORGE_EDGE_REJECT_RADIUS`（默认 2）或调小
`SPINEFORGE_EDGE_GRADIENT_THRESHOLD`（默认 3000）。两者都会剔除更多像素，
代价是覆盖率下降、更多区域要靠扩散填。

### 关节处看起来"断开"

膝盖、脚踝、袖口这些位置，如果原画是靠颜色过渡连成一体的，
就要把相邻部件写进概念的 `groups`。同组部件在 ControlNet 控制图里共享一个 ID，
接缝处不会产生边界线，SD 也就不会沿着接缝画出分界。

### 多轮之后颜色漂移

检查 `report.json` 的 `rejected_dup`。它统计的是"这个纹素前面已经写过了"的次数，
数值大是正常的（后续姿势本来就大量重复暴露同一批纹素）。
如果贴图仍在漂，说明写入去重失效了，去看 `writeback.apply_frame` 里的 `written` 字典。

### SD 出的图和画布对不上

`reskin` 会直接报错。检查画布宽高是不是 `8 * downscale` 的倍数，
以及 WebUI 那边有没有被别的扩展改了输出尺寸。

## 排查路径

`build/<角色>/skins/<换装>_<seed>/steps/` 下按姿势序号存了四张图：

| 文件 | 看什么 |
| --- | --- |
| `*_base.png` | 送给 SD 的底图。第 0 帧是原始贴图的渲染，之后是"画了一半"的渲染 |
| `*_mask.png` | 白色区域是这一帧要重绘的。全黑说明没有新纹素，序列该结束了 |
| `*_canny.png` | ControlNet 输入。线条断裂或缺失说明部件分组或 alpha 阈值有问题 |
| `*_redraw.png` | SD 的输出。这张不对就是 prompt / 模型 / 强度的问题，和本流水线无关 |

配合 `redraw/<换装>/manifest.json` 的 `ids` 表，可以把 `uv.npy` 里任意一个像素
反查到具体部件和纹素下标。

## 接入现有 Spine 工程

目前 `preprocess` / `reskin` / `preview` 只依赖四样东西：
`skeleton.json`、`images/` 下的 attachment 贴图、哪些部件要重绘、以及部件分组。
概念文件的作用就是提供后两样。理论上换成美术手里的真实工程即可，
但落地前还有两个缺口：

**运行时只支持 region attachment。** 真实项目里大量使用 mesh attachment
（带权重的网格变形），`spineforge/runtime.py` 需要补上顶点权重解算和 deform 时间轴，
`raster.py` 的三角形遍历本身已经是通用的，不用改。

**需要一个导入命令。** 从现有 `skeleton.json` 反推出一份概念文件（slot 列表、
绑定骨骼、贴图尺寸），把 `redraw` 标记和 `groups` 留给美术填。
在此之前可以手写概念文件，把 `build` 跳过、直接把工程文件放到 `build/<角色>/` 下。
