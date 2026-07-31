# AGENTS

## Cursor Cloud specific instructions

本仓库是一套动画角色设定资料集（Markdown 文档 + SVG 素材），不是传统的可运行服务。

- **唯一的「程序」**：`tools/gen_visuals.py`，由 `tools/palettes.json` 生成 `assets/palettes/*.svg` 与 `assets/proportions.svg`。
- **依赖**：只用 Python 3 标准库（环境已装 Python 3.12），无第三方包、无 lock 文件、无 npm/pip 依赖，因此没有可安装的依赖，也没有独立的 lint / 测试框架。
- **运行 / 「构建」**（在仓库根目录执行，见 `README.md`）：

```bash
python3 tools/gen_visuals.py
```

  运行后若 `git status` 干净，说明生成结果与已提交的 SVG 一致，即环境正常。

- **色号是单一真实来源**：只在 `tools/palettes.json` 改 HEX；改身高/头身比时需同步更新 `tools/gen_visuals.py` 里的 `FIGURES` 表和对应角色文档，然后重新跑上面的脚本。
- **预览 SVG（可选，非项目依赖）**：仓库本身不需要任何渲染器。若只是想把 SVG 转成 PNG 查看，可临时 `sudo apt-get install -y librsvg2-bin` 后用 `rsvg-convert in.svg -o out.png`；不要把它写进更新脚本。
