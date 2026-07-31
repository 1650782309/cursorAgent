# spineforge —— Spine 动画自动生成与 SD 换装

由本仓库的**角色设定集**驱动的 Spine 动画自动生成 + Stable Diffusion 换装工作流。

输入是仓库里已有的角色设定集：`tools/palettes.json` 提供配色与头身比，
`concepts/<角色>.yaml` 补上部件拆分与换装预设。输出是一整套 attachment 贴图、
一份可导入 Spine 编辑器的 `skeleton.json`（含程序化生成的 idle / walk / run / wave / cast 等动画），
以及任意套数的 AI 重绘换装贴图。

配色与头身比**不在概念文件里重复**，一律从 `tools/palettes.json` 现取——
这是设定集 README 定下的规矩。改那份 JSON 里的色号，重新 build 一次贴图就跟着变。

换装部分的算法移植自 [RedrawSpine](https://github.com/Zhangyangrui916/RedrawSpine)：
建立**贴图 UV ↔ 画面像素**的映射，在多个关键姿势上分别重绘，再把结果沿映射写回 attachment。
原实现是 OpenGL + CUDA 的 C++ analyzer，依赖 Spine 编辑器和 Photoshop；
这里全部改写成 numpy 软件渲染，**不需要 GPU、Spine 编辑器和 Photoshop 也能跑通全流程**。

---

## 快速开始

```bash
pip install -r requirements.txt

python -m spineforge list                        # 看看有哪些角色和换装预设
python -m spineforge show akari                  # 灯莉的部件表、绘制顺序、哪些部件保形
python -m spineforge run akari field_work        # 一条龙：建模 -> 预处理 -> 换装 -> 预览
```

产物在 `build/akari/skins/field_work_0/`：`images/` 是新贴图，
`preview/` 是各动画 GIF 和关键姿势对照图，`steps/` 是逐姿势的中间图（底图 / mask / canny / 重绘结果）。

上面用的是**离线 mock 后端**，不需要显卡。要接真正的 SD：

```bash
# 先启动 Stable Diffusion WebUI（带 --api 与 ControlNet 扩展）
python -m spineforge reskin akari field_work --seed 12345 --backend webui --preview
```

---

## 流水线

```
tools/palettes.json  ──┐   配色 + 头身比（设定集的唯一真实来源）
concepts/<角色>.yaml ──┤   部件拆分 + 换装预设
                       │
        ├── build ─────────► build/<角色>/images/*.png      每个部件一张贴图
        │                    build/<角色>/skeleton.json     骨架 + 全部动画
        │                    build/<角色>/images/fake.atlas
        │
        ├── preprocess ────► build/<角色>/redraw/<换装>/
        │                      restPose.uv.npy   UV 映射（部件ID<<24 | 纹素下标）
        │                      restPose@mask.png inpaint 遮罩
        │                      restPose@ctrl.png 分组 ID 图
        │                      restPose@canny.png ControlNet 输入
        │                      manifest.json     姿势序列 / ID 表 / 覆盖率
        │
        ├── reskin ────────► build/<角色>/skins/<换装>_<seed>/
        │                      images/  换装后的整套贴图
        │                      steps/   逐姿势中间图
        │                      report.json
        │
        └── preview ───────► GIF + 关键姿势对照图
```

### 1. build

按设定集里的**头身比**推出骨架比例——躯干链恒定占 3.1 个头长
（头 1.0 + 颈 0.25 + 胸 0.85 + 腰腹 1.0），剩下的全归腿，
所以 5.5 头身的忍和 8.0 头身的伊卡洛斯得到的骨架明显不同。
身高按 `px_per_cm` 换算成像素，178 cm 的墨在画面上确实比 142 cm 的忍高一头。

然后按 `parts` 生成贴图并挂到对应骨骼上，再按 `animations` 列表生成动画时间轴。动画是解析式的（正弦摆动、缓动抬手等）
在关键帧上采样出来的，采样点之间用线性插值，因此导出的 JSON 在 Spine 编辑器里
播放和在本仓库运行时里播放完全一致。

这一步还会扫描全部动画的包围盒，画布兜不住时给出告警——超出画布的部分不会参与重绘。

### 2. preprocess：为什么要选关键姿势

一张 attachment 贴图上的纹素，在正面站姿里往往只露出一部分：手臂内侧、裙子背面、
被躯干挡住的袖子。只重绘一张正面图，这些纹素永远是空白。

所以要贪心地找姿势：先把 rest pose 能看到的纹素全部标记为"已画"，
然后遍历所有动画的所有采样时刻，挑出**还没画过的纹素露出最多**的那一帧，
加进序列并同样标记，如此反复，直到某一轮的新增收益低到不值得再做一次 SD 推理。

`manifest.json` 里的 `coverage` 会告诉你每个部件被覆盖了多少。
覆盖率低的部件说明现有动画根本没展示过它，需要美术补一个展示姿势，
否则那块贴图只能靠邻域扩散猜颜色。

### 3. reskin：逐姿势重绘并回写

```
洗白待重绘的 attachment
   │
   ├─ 姿势 0：拿原始贴图的 rest pose 渲染当底图，整体 inpaint
   │     └─ 沿 UV 映射把结果写回 attachment
   │
   ├─ 姿势 i：拿"已经画了一部分"的 attachment 渲染出这一帧
   │     ├─ mask = 这一帧里还没画过的纹素
   │     ├─ canny = 分组 ID 图的边界，作为 ControlNet 输入锁形状
   │     └─ 局部 inpaint -> 回写
   │
   └─ 收尾：仍未被覆盖的纹素用邻域颜色扩散填充
```

回写这一步有两个约束，少一个贴图就会脏：

**边缘像素不能写回。** 落在部件轮廓上的像素混了旁边部件甚至背景的颜色，
写回去会在贴图边缘糊出脏边。判据在 HSV 空间做——SD 输出的同一块布料常有明度渐变
但色相稳定，用 RGB 判据会把正常的受光面误判成边界。

**同一个纹素只写第一次。** 一个纹素可能在好几个姿势里都可见，
反复覆盖会让颜色在多轮之后逐渐漂移。

### 4. preview

用任意一套贴图渲染动画 GIF 和关键姿势对照图，用来确认换装后动起来没有穿帮。

---

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `spineforge list` | 列出概念库 |
| `spineforge show <角色>` | 查看部件表、绘制顺序、哪些部件保形 |
| `spineforge build [角色\|all]` | 生成贴图 + 骨架 + 动画 |
| `spineforge preprocess <角色> --outfit <换装>` | 选关键姿势，看覆盖率 |
| `spineforge reskin <角色> <换装> --seed N --backend mock\|webui` | 换装 |
| `spineforge preview <角色> [--images 目录]` | 渲染 GIF 与对照图 |
| `spineforge run <角色> <换装>` | 以上四步一条龙 |

批量出图就是循环 seed：

```bash
for s in $(seq 100 130); do
  python -m spineforge reskin akari field_work --seed $s --backend webui --no-steps
done
```

---

## 配置

`spineforge/config.py` 里的每个字段都能用 `SPINEFORGE_<大写字段名>` 环境变量覆盖：

```bash
export SPINEFORGE_SD_HOST=192.168.1.20
export SPINEFORGE_SD_MODEL="meinapastel_v6Pastel.safetensors"
export SPINEFORGE_DOWNSCALE=2          # 送进 SD 前的降采样倍数，越大越省显存
export SPINEFORGE_DENOISING_STRENGTH=0.72
export SPINEFORGE_KEYPOSE_MAX_COUNT=8  # 最多选几个关键姿势
```

几个容易踩的点：

* 画布宽高必须是 `8 * downscale` 的倍数。不是的话 SD 会自行 padding，
  返回的图和 mask 差几个像素，UV 回写就整体错位了。
* WebUI 后端固定用 `inpaint_full_res=False`。开启后 WebUI 会先裁剪再缩放回来，
  结果和 mask 对不上。这是 RedrawSpine 踩过的坑，这里沿用它的结论。
* `inpainting_fill=1`（潜空间噪声）。洗白后的底图是纯白，用原图填充 SD 画不出东西。

---

## 新增一个角色

前提：这个角色已经进了设定集（`tools/palettes.json` 里有配色与头身比，
`docs/<企划>/` 下有设定文档）。

1. 抄一份 `concepts/akari.yaml` 改名，把 `bible` 指向设定集里的条目，
   字段含义见 [`concepts/_schema.md`](../concepts/_schema.md)。
2. 用 `aliases` 给设定集的机械配色名起可读的名字（`hanten: costume_3`）。
   写错时报错会列出设定集给的全部键及其用途，照着改即可。
3. 按设定文档的"外貌设计"逐条拆成 `parts`。
   照抄设定里的部位描述比自己发明更省事——比如忍"膝盖以下化为淡雾、不画脚"，
   那份概念里就一个 foot 部件都没有。
4. `python -m spineforge build <新角色> && python -m spineforge preview <新角色>`，
   看对照图确认部件位置对不对。
5. 把脸、瞳孔、头发、以及设定里"唯一的高饱和色"标上 `redraw: false`——
   它们会作为遮挡体参与渲染，但不会被 SD 改动。
   冴的红臂章和伊卡洛斯的胸口宝石就是靠这条守住配色纪律的。
6. 把会被误判成接缝的部件分组写进 `groups`。例如紧身裤加长筒军靴在原画里是
   连续的深色，不分组的话 canny 会在膝盖画出横线，重绘后关节看起来是"断开"的。
7. `python -m spineforge preprocess <新角色> --outfit <换装>` 看覆盖率，偏低就补动画。
8. 换装预设直接照设定文档里的**服装差分表**写，
   `negative_prompt` 里要带上设定明令禁止的元素（伊卡洛斯的机械翅膀、纯黑、粉色服装）。

## 开发

```bash
python -m pytest tests -q
```

测试覆盖概念校验、骨架/动画生成、UV 映射与回写的逐像素往返，
以及用 mock 后端跑完整条流水线的冒烟测试。全部离线，不需要 SD。
