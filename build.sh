#!/bin/bash
# ============================================================================
#  构建「应用提取器」的 .fpk 安装包
#
#  依赖：官方打包工具 fnpack
#    · Windows 版已随仓库放在 tools/fnpack.exe
#    · Linux / macOS 可从 https://developer.fnnas.com/docs/cli/fnpack/ 下载
#
#  用法：bash build.sh
#  产物：<项目根>/fpk-extractor_<版本>_<平台>.fpk
# ============================================================================
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/source/fpk-extractor"

# ---------------------------------------------------------------- 找 fnpack
FN=""
for c in "$ROOT/tools/fnpack.exe" "$ROOT/tools/fnpack"; do
    if [ -x "$c" ]; then FN="$c"; break; fi
done
if [ -z "$FN" ]; then
    if command -v fnpack >/dev/null 2>&1; then
        FN="$(command -v fnpack)"
    else
        echo "错误：未找到 fnpack。请把 fnpack 放到 tools/ 目录，或安装到 PATH。" >&2
        exit 1
    fi
fi
echo "使用打包工具：$FN"

# ---------------------------------------------------------------- 生成图标
PY=""
for c in python3 python py; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -n "$PY" ]; then
    "$PY" "$ROOT/source/gen-icon.py" "$SRC"
    mkdir -p "$SRC/app/ui/images" "$SRC/app/bin/fallback"
    cp -f "$SRC/ICON.PNG"     "$SRC/app/ui/images/64.png"
    cp -f "$SRC/ICON_256.PNG" "$SRC/app/ui/images/256.png"
    cp -f "$SRC/ICON.PNG" "$SRC/ICON_256.PNG" "$SRC/app/bin/fallback/"
else
    echo "提示：未找到 python，跳过图标生成（沿用现有图标）"
fi

# ---------------------------------------------------------------- 清理缓存
# 本地跑过 py_compile / 服务后会产生 __pycache__，绝不能打进安装包
find "$SRC" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$SRC" -type f -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$SRC/app/server/__pycache__" 2>/dev/null || true

# ---------------------------------------------------------------- 打包
VER="$(sed -n 's/^version[[:space:]]*=[[:space:]]*//p' "$SRC/manifest" | head -n 1 | tr -d '[:space:]')"
PLAT="$(sed -n 's/^platform[[:space:]]*=[[:space:]]*//p' "$SRC/manifest" | head -n 1 | tr -d '[:space:]')"
[ -n "$VER" ] || VER="0.0.0"
[ -n "$PLAT" ] || PLAT="all"

rm -f "$SRC"/*.fpk
( cd "$SRC" && "$FN" build )

BUILT="$SRC/fpk-extractor.fpk"
[ -f "$BUILT" ] || { echo "错误：未生成 fpk" >&2; exit 1; }

# ---------------------------------------------------------------- 兼容补丁
# fnpack 会把 app/ui 打进 app.tgz（安装后即 target/ui，对应 desktop_uidir=ui，
# 这是官方约定）；社区包习惯在「包根」再放一份 ui/。两处内容相同最保险，
# 所以这里把 ui/ 追加到包根。app.tgz 未被改动，manifest 里的 checksum 仍然有效。
has_root_ui() { tar tzf "$1" 2>/dev/null | grep -qE '^/?ui/?$'; }

if has_root_ui "$BUILT"; then
    echo "包根已含 ui/，无需补丁"
else
    PATCHD="$(mktemp -d)"
    if tar xzf "$BUILT" -C "$PATCHD" app.tgz 2>/dev/null \
       && tar tzf "$PATCHD/app.tgz" 2>/dev/null | grep -qE '^/?ui/?$'; then
        tar xzf "$PATCHD/app.tgz" -C "$PATCHD" ui 2>/dev/null
        gunzip -c "$BUILT" >"$PATCHD/pkg.tar"
        tar rf "$PATCHD/pkg.tar" -C "$PATCHD" ui
        gzip -9 -c "$PATCHD/pkg.tar" >"$PATCHD/pkg.fpk"
        mv -f "$PATCHD/pkg.fpk" "$BUILT"
        echo "已在包根补一份 ui/（兼容社区包布局）"
    fi
    rm -rf "$PATCHD"
fi

OUT="$ROOT/fpk-extractor_${VER}_${PLAT}.fpk"
cp -f "$BUILT" "$OUT"
rm -f "$BUILT"

echo
echo "✅ 构建完成：$OUT"
echo "   大小：$(wc -c <"$OUT" | tr -d ' ') 字节"
