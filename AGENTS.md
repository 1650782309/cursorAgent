# AGENTS

## Cursor Cloud specific instructions

本仓库是一套动画／游戏角色设定资料集（Markdown 文档 + SVG 素材 + 少量 PNG 立绘），不是传统的可运行服务。

- **仓库收录多个互不相关的企划**，世界观独立；**作画基线统一为 TV 动画赛璐璐**（见各企划 `03` / 雾见町 `05`）：
  - `docs/kirimicho` + `assets/kirimicho` —《雾见町 遗物招领所》（深夜档 TV 动画）
  - `docs/icarus` + `assets/icarus` —《黄昏之羽》（TV 动画，与左共用作画规范）
- **唯一的「程序」**：`tools/gen_visuals.py`，由 `tools/palettes.json` 生成
  `assets/<企划 id>/palettes/*.svg` 与 `assets/<企划 id>/proportions.svg`。
- **依赖**：只用 Python 3 标准库（环境已装 Python 3.12），无第三方包、无 lock 文件、无 npm/pip 依赖，因此没有可安装的依赖，也没有独立的 lint / 测试框架。
- **运行 /「构建」**（在仓库根目录执行，见 `README.md`）：

```bash
python3 tools/gen_visuals.py
```

  运行后若 `git status` 干净，说明生成结果与已提交的 SVG 一致，即环境正常。

- **色号是单一真实来源**：只在 `tools/palettes.json` 改 HEX。身高与头身比同样在该文件的
  `works.<企划 id>.proportions` 中维护，改完需同步更新对应角色文档，然后重新跑上面的脚本。
- **新增企划**：在 `tools/palettes.json` 的 `works` 下加一个条目即可，输出路径会自动变为
  `assets/<企划 id>/`；文档放到 `docs/<企划 id>/`，并在 `README.md` 的企划表格中登记。
- **预览 SVG（可选，非项目依赖）**：仓库本身不需要任何渲染器。若只是想把 SVG 转成 PNG 查看，
  可临时 `sudo apt-get install -y librsvg2-bin` 后用 `rsvg-convert in.svg -o out.png`；
  不要把它写进更新脚本。SVG 中的中文依赖系统安装了 CJK 字体，缺字体时预览会显示方框，
  属正常现象，不要因此修改 SVG。
