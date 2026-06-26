#!/usr/bin/env bash
# 一键配置依赖：检查 Python / ffmpeg / ffprobe，缺失则自动 brew install
# 用法：bash setup.sh
set -e

set +e
BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'
set -e

say()   { echo -e "${BOLD}$*${RESET}"; }
ok()    { echo -e "${GREEN}✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}⚠${RESET} $*"; }
die()   { echo -e "${RED}✗${RESET} $*" >&2; exit 1; }

# ---- 进入项目目录 ----
cd "$(dirname "$0")"
PROJECT="$(pwd)"
say "BiliBiliVideo-TRANS 配置"
echo "项目目录: $PROJECT"
echo

# ---- 检查 Python ----
say "[1/3] 检查 Python"
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "未知")
    PY_MAJOR=$(python3 -c 'import sys;print(sys.version_info[0])' 2>/dev/null || echo 0)
    PY_MINOR=$(python3 -c 'import sys;print(sys.version_info[1])' 2>/dev/null || echo 0)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 9 ] 2>/dev/null; then
        ok "Python $PY_VER"
    else
        die "Python $PY_VER 版本过低，需要 3.9+。请用 brew install python 升级"
    fi
else
    die "未找到 python3。macOS 安装：brew install python"
fi
echo

# ---- 检查 ffmpeg ----
say "[2/3] 检查 ffmpeg / ffprobe"
MISSING_FFMPEG=0
if ! command -v ffmpeg >/dev/null 2>&1; then
    warn "未找到 ffmpeg"
    MISSING_FFMPEG=1
else
    ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
fi
if ! command -v ffprobe >/dev/null 2>&1; then
    warn "未找到 ffprobe"
    MISSING_FFMPEG=1
else
    ok "ffprobe $(ffprobe -version 2>&1 | head -1 | awk '{print $3}')"
fi

if [ "$MISSING_FFMPEG" -eq 1 ]; then
    if ! command -v brew >/dev/null 2>&1; then
        die "未找到 Homebrew。请先安装：https://brew.sh\n  然后运行：brew install ffmpeg"
    fi
    say "通过 Homebrew 安装 ffmpeg（包含 ffprobe）..."
    brew install ffmpeg
    command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg 安装失败"
    ok "ffmpeg 安装完成"
fi
echo

# ---- 准备目录 ----
say "[3/3] 准备目录"
mkdir -p input_folder output_video
ok "input_folder/  (把 cid 文件夹拖进来)"
ok "output_video/  (合并后的 mp4 会在这里)"
echo

say "${GREEN}配置完成！${RESET}"
echo
echo "下一步："
echo "  1. 把 Bilibili 客户端下载的 cid 文件夹放进 input_folder/"
echo "  2. 运行：python3 merge.py"
echo "  3. 在 output_video/ 取合并好的 mp4"
