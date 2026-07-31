# 本地安装

分两段：先把**离线部分**装通（不需要显卡，五个角色的换装全流程都能跑），
确认没问题之后再接 **Stable Diffusion**。不要一上来就两件事一起弄——
出了问题分不清是哪一边的。

## 一、离线部分

需要 Python 3.10 以上。除此之外没有别的系统依赖：没有 GPU 要求，
不需要装 Spine 编辑器，也不需要 Photoshop。

### macOS / Linux

```bash
git clone https://github.com/1650782309/cursorAgent.git
cd cursorAgent
git checkout cursor/spine-anim-autogen-workflow-0ab7

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

spineforge doctor
```

### Windows（PowerShell）

```powershell
git clone https://github.com/1650782309/cursorAgent.git
cd cursorAgent
git checkout cursor/spine-anim-autogen-workflow-0ab7

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

spineforge doctor
```

`spineforge doctor` 会逐项检查 Python 版本、四个依赖、角色设定集与概念库能否解析、
画布尺寸是否对齐、产物目录是否可写。全绿了再往下走：

```bash
spineforge run akari field_work
```

产物在 `build/akari/skins/field_work_0/`：

| 目录 | 内容 |
| --- | --- |
| `images/` | 换装后的整套 attachment 贴图，可直接拖进 Spine 编辑器 |
| `preview/` | 各动画的 GIF 与关键姿势对照图 |
| `steps/` | 逐姿势的中间图：底图 / 遮罩 / ControlNet 边缘 / 重绘结果 |
| `report.json` | 关键姿势数、回写纹素数、逐部件覆盖率 |

想一次看全五个角色和全部 13 套换装：

```bash
spineforge build all
python3 - <<'EOF'
import subprocess
from spineforge.concept import list_concepts
for c in list_concepts():
    for o in c.outfits:
        subprocess.run(["spineforge", "reskin", c.id, o, "--seed", "0",
                        "--backend", "mock", "--no-steps"])
EOF
python3 tools/gen_spine_demo.py
```

四张演示图会写到 `build/demo/`。

### 为什么用 `pip install -e .`

角色设定集（`tools/palettes.json`）和概念库（`concepts/`）是**数据不是代码**，
不会被打进 wheel。可编辑安装让源码树留在原地，所以你改设定集的色号、
改概念文件的部件拆分，重新 build 一次就生效，不用重装。

如果不想装包，直接 `pip install -r requirements.txt`
然后用 `python -m spineforge ...` 也完全一样，只是没有 `spineforge` 这个短命令。

---

## 二、接 Stable Diffusion

上面用的是**离线 mock 后端**——它做确定性的配色替换，用来验证管线本身
（UV 映射对不对、回写有没有落到正确的纹素、保形部件有没有被动到）。
真正的布料质感、褶皱、花纹要靠 SD 画。

### 需要什么

1. **AUTOMATIC1111 Stable Diffusion WebUI**，启动时带 `--api`：

   ```bash
   ./webui.sh --api          # Windows: webui-user.bat 里加 --api 到 COMMANDLINE_ARGS
   ```

2. **sd-webui-controlnet 扩展**，以及一个 **canny** 控制模型
   （例如 `control_v11p_sd15_canny`）。控制图用来锁住重绘时的部件轮廓，
   没有它 SD 会把衣服画到轮廓外面去。

3. 一个动漫向的底模。设定集要求画风是 TV 赛璐璐（硬边阴影、扁平色块），
   所以底模也该选这个路子的。

### 配置

所有配置项都能用 `SPINEFORGE_<大写字段名>` 环境变量覆盖，字段见
`spineforge/config.py`。常用的几个：

```bash
export SPINEFORGE_SD_HOST=127.0.0.1
export SPINEFORGE_SD_PORT=7860
export SPINEFORGE_SD_MODEL="meinapastel_v6Pastel.safetensors [4679331655]"
export SPINEFORGE_CONTROLNET_CANNY_MODEL="control_v11p_sd15_canny [d14c016b]"
export SPINEFORGE_DOWNSCALE=2            # 送进 SD 前降采样几倍，越大越省显存
export SPINEFORGE_DENOISING_STRENGTH=0.72
```

模型名要和 WebUI 下拉框里**完全一致**，包括后面的 `[hash]`。

### 验证

```bash
spineforge doctor --sd
```

它会依次确认：API 通不通、指定的底模在不在、ControlNet 扩展装没装、
配置的 canny 模型存不存在、超分模型有没有。任何一项不过都会给出具体怎么改，
canny 模型对不上时还会把你 WebUI 里实际有的模型名列出来。

全绿之后：

```bash
spineforge reskin akari field_work --seed 12345 --backend webui --preview
```

批量出图就是循环 seed：

```bash
for s in $(seq 100 130); do
  spineforge reskin akari field_work --seed $s --backend webui --no-steps
done
```

---

## 常见问题

**`spineforge: command not found`**
虚拟环境没激活，或者装的时候没进虚拟环境。`source .venv/bin/activate` 后重试；
也可以直接用 `python -m spineforge`，效果一样。

**`找不到角色设定集`**
命令要在克隆出来的仓库目录里跑（或其任意子目录）。这套流程的输入是仓库里的数据文件，
装到别处的话它找不到 `tools/palettes.json`。

**显存不够**
调大 `SPINEFORGE_DOWNSCALE`（默认 2）。它只影响送进 SD 的分辨率，
出图后会放大回画布尺寸再回写。注意画布宽高必须是 `8 * downscale` 的倍数，
`spineforge doctor` 会检查这一条。

**换装结果和遮罩对不上、整个贴图错位**
多半是 SD 那边返回的图尺寸和画布不一致。`reskin` 会直接报错而不是默默写坏贴图。
检查画布对齐，以及 WebUI 有没有被别的扩展改了输出尺寸。

**贴图上有大片没被画到的区域**
看 `report.json` 里的 `coverage.per_part`。覆盖率低说明那个部件在现有动画里
就没怎么露出来，只能靠邻域扩散猜色。解决办法是给概念补一段展示该部位的动画，
细节见 [WORKFLOW.md](WORKFLOW.md)。

**想换成自己的角色**
见 [spineforge.md](spineforge.md) 的「新增一个角色」。前提是角色已经进了设定集
（`tools/palettes.json` 里有配色与头身比）。
