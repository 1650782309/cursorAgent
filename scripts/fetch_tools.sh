#!/usr/bin/env bash
# 拉取流水线依赖的外部工具（从 GitHub Release）。
#
#   scripts/fetch_tools.sh            # 下载到 ./vendor
#   scripts/fetch_tools.sh -d ~/tools # 指定目录
#
# 只做下载与解压，不做安装。IDA/Ghidra/RenderDoc/BepInEx 请按各自方式单独装。
set -euo pipefail

DEST="vendor"
while getopts "d:h" opt; do
  case "$opt" in
    d) DEST="$OPTARG" ;;
    h) sed -n '2,10p' "$0"; exit 0 ;;
    *) exit 1 ;;
  esac
done

mkdir -p "$DEST"
cd "$DEST"

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少 $1"; exit 1; }; }
need curl
need unzip

# repo, 资产名匹配串, 落地目录
TOOLS=(
  "Perfare/Il2CppDumper|net8|Il2CppDumper"
  "Perfare/AssetStudio|net8|AssetStudio"
  "AssetRipper/AssetRipper|linux_x64|AssetRipper"
  "SamboyCoding/Cpp2IL|Linux|Cpp2IL"
  "icsharpcode/ILSpy|ilspycmd|ILSpy"
)

fetch() {
  local repo="$1" match="$2" dir="$3"
  echo "==> $repo"
  local url
  url=$(curl -fsSL "https://api.github.com/repos/${repo}/releases/latest" \
    | grep -o '"browser_download_url": *"[^"]*"' \
    | cut -d'"' -f4 \
    | grep -i -- "$match" \
    | head -1 || true)
  if [[ -z "$url" ]]; then
    echo "    未找到匹配 '$match' 的资产，手动下载: https://github.com/${repo}/releases/latest"
    return
  fi
  local file="${url##*/}"
  [[ -f "$file" ]] || curl -fL --retry 3 -o "$file" "$url"
  mkdir -p "$dir"
  case "$file" in
    *.zip) unzip -oq "$file" -d "$dir" ;;
    *.tar.gz|*.tgz) tar xzf "$file" -C "$dir" ;;
    *) mv -f "$file" "$dir/" ;;
  esac
  echo "    -> $dir"
}

for t in "${TOOLS[@]}"; do
  IFS='|' read -r repo match dir <<<"$t"
  fetch "$repo" "$match" "$dir"
done

cat <<'EOF'

下载完成。还需要单独安装的：
  IDA Pro / Ghidra   反汇编，读 IL2CPP 逻辑的主战场
  BepInEx + UnityExplorer   PC 运行时对象树（Mono 用 BepInEx 5，IL2CPP 用 BepInEx 6）
  Frida              pip install frida-tools，移动端还需 push frida-server
  RenderDoc          抓帧看渲染管线
  mitmproxy          pip install mitmproxy

Python 侧：
  pip install -e tools/[assets]
EOF
