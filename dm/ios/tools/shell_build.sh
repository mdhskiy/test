#!/bin/bash
# 出「壳」：一个不含任何游戏内容、没有签名的 iOS 安装包（zip，构建原料）。之后用 scripts/d3rm_pack.py 在 Windows 上
# 把自己的游戏文件做进去，再用自签工具（iLoader / AltStore / Sideloadly）整包签名装机——全程不需要 Xcode，也不需要 Mac。
#   shell_build.sh [输出.zip]    缺省 $DM_ROOT/build/shell/DmIOS-shell-build-input.zip
# 环境：GAME = 游戏档案（dm/games/<标题号> 或 DM_GAMES_DIR 里的；必给，壳的内存 / NVN 常量按它编），DM_ROOT = 工作根目录
# 产物：壳 zip（Payload/DmIOS.app + dm/shell_manifest.txt + dm/shell_info.txt）、shell_manifest.txt、shell_info.txt（副本，便于查看）
# 壳里有的：宿主全部源码编出的可执行文件、通用字体（standard / nintendo_ext）、触控与手柄前端。没有：游戏程序、着色器库、改写表、RomFS、图标。
# Build the "shell": an unsigned iOS install package (a zip, build input) with no game content at all. scripts/d3rm_pack.py then builds your
# own game files into it on Windows, and a sideloading tool (iLoader / AltStore / Sideloadly) signs the whole package -- no Xcode, no Mac needed.
#   shell_build.sh [output.zip]    default $DM_ROOT/build/shell/DmIOS-shell-build-input.zip
# Environment: GAME = game profile (dm/games/<title ID> or one in DM_GAMES_DIR; required -- the shell's memory / NVN constants are compiled for it),
#   DM_ROOT = workspace root
# Output: the shell zip (Payload/DmIOS.app + dm/shell_manifest.txt + dm/shell_info.txt), plus copies of the manifest and info for inspection.
# The shell contains: the host executable built from all host sources, the generic fonts (standard / nintendo_ext), the touch and gamepad frontends.
# It does not contain: the game program, shader libraries, rewriter tables, RomFS, or an icon.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); IOS=$HERE/..; DM=$(cd "$IOS/.." && pwd)
t() { echo "[$(date +%T)] $*"; }; die() { t "FAIL: $*"; exit 1; }
[ -n "${GAME:-}" ] || die "GAME is not set: GAME=<base game title ID> shell_build.sh"
GD=$(python3 "$DM/games/game.py" dir "$GAME") || die "no game profile $GAME"
[ -f "$GD/game.tsv" ] || die "no game profile $GD/game.tsv"
ROOT=${DM_ROOT:-$HOME/dm-work}; O=$ROOT/build/shell; mkdir -p "$O"
OUT=${1:-$O/DmIOS-shell-build-input.zip}
for tool in xcodegen xcodebuild python3 make clang; do command -v $tool > /dev/null || die "缺工具 ${tool}（装 Xcode / xcodegen：brew install xcodegen）"; done
# 壳的包名 / 团队号只是占位：自签工具装机时会换成使用者自己的 | the shell's bundle ID / team ID are placeholders; the sideloading tool replaces them at install time
export DM_TEAM_ID=0000000000 DM_BUNDLE_ID=org.dmios.app DM_DISPLAY_NAME=${DM_DISPLAY_NAME:-$(python3 "$DM/games/game.py" "$GAME" app_name 2>/dev/null || echo Dm)} DM_APP_VERSION=1.0 \
       DM_APP_CATEGORY=$(python3 "$DM/games/game.py" "$GAME" app_category) DM_FREE_ACCOUNT=1
cd "$IOS" || die "cd $IOS"

t "生成 Gen/（宿主源码清单 + 配置；壳没有游戏内容）"
rm -rf Gen && mkdir -p Gen/dm Gen/msl Gen/Assets.xcassets || die "mkdir Gen"
python3 tools/gen_build.py ../host Gen > Gen/dm.xcconfig || die "gen_build"
# 模块映像不进可执行文件：内嵌汇编清空、去掉 segprot 链接参数；打开装载器的壳分支（loader.c 的 DM_SHELL 分支，从 Frameworks/Guest.framework/Guest 取段）
# The module images do not go into the executable: empty the embedded assembly and drop the segprot link flags; turn on the loader's shell branch
# (the DM_SHELL branch of loader.c takes the segments from Frameworks/Guest.framework/Guest)
echo '// 壳：模块映像不在可执行文件里（ios/tools/shell_build.sh；游戏程序由 scripts/d3rm_pack.py 做成 Guest.framework 放进安装包）' > Gen/embed.S
echo "OTHER_CFLAGS = \$(inherited) -DDM_SHELL" >> Gen/dm.xcconfig
grep -q -- '-DDM_SHELL' Gen/dm.xcconfig || die "构建配置没改对：$(grep -n OTHER_ Gen/dm.xcconfig)"
printf '{"info":{"author":"xcode","version":1}}\n' > Gen/Assets.xcassets/Contents.json
ICON=$GD/icon.png
if [ -f "$ICON" ]; then
  mkdir -p Gen/Assets.xcassets/AppIcon.appiconset
  cp "$ICON" Gen/Assets.xcassets/AppIcon.appiconset/icon1024.png
  printf '{"images":[{"filename":"icon1024.png","idiom":"universal","platform":"ios","size":"1024x1024"}],"info":{"author":"xcode","version":1}}\n' > Gen/Assets.xcassets/AppIcon.appiconset/Contents.json
  echo "DM_APPICON = AppIcon" >> Gen/dm.xcconfig
  t "图标 $(python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(33); w,h=struct.unpack('>II', d[16:24]); print(f'{w}x{h}')" "$ICON") → AppIcon"
fi
# 通用字体随壳走（不是游戏内容）：standard = macOS 的 Arial Unicode，nintendo_ext = 按钮图标（fontTools 生成）
# The generic fonts travel with the shell (not game content): standard = macOS's Arial Unicode, nintendo_ext = button icons (needs fontTools)
mkdir -p Gen/dm/font
STD=${STD_FONT:-/System/Library/Fonts/Supplemental/Arial Unicode.ttf}
if [ ! -f "$STD" ]; then   # macOS 15 may not ship Arial Unicode: fall back to another system TTF
  for c in "/System/Library/Fonts/Supplemental/Arial.ttf" "/System/Library/Fonts/Supplemental/Verdana.ttf" "/System/Library/Fonts/Supplemental/Times New Roman.ttf"; do
    [ -f "$c" ] && { t "标准字体回退到 $c"; STD=$c; break; }
  done
fi
[ -f "$STD" ] || die "找不到标准字体：用 STD_FONT=<一个 TTF> 指定"
cp "$STD" Gen/dm/font/standard.ttf || die "copy standard font"
${FONT_PY:-python3} "$DM/tools/make_ext_font.py" Gen/dm/font/nintendo_ext.ttf > /dev/null || die "make_ext_font.py (pip install fonttools, or FONT_PY=python with fontTools)"

t "xcodegen"
xcodegen generate -q > /dev/null || die "xcodegen"
t "xcodebuild（不签名，iPhone + iPad）"
DD=$O/dd; mkdir -p "$DD"
xcodebuild -project DmIOS.xcodeproj -scheme DmIOS -configuration Release -destination 'generic/platform=iOS' -derivedDataPath "$DD" \
  DM_DEVICE_FAMILY=1,2 CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= build > "$O/build.log" 2>&1 \
  || { grep -E 'error:' "$O/build.log" | head -10; die "xcodebuild, log $O/build.log"; }
APP=$DD/Build/Products/Release-iphoneos/DmIOS.app; [ -d "$APP" ] || APP=$(grep -o '/[^ ]*/Release-iphoneos/DmIOS\.app' "$O/build.log" | tail -1)
[ -d "$APP" ] || die "no built app"
rm -rf "$O/Payload" && mkdir -p "$O/Payload" && cp -R "$APP" "$O/Payload/DmIOS.app" || die "copy app"
A=$O/Payload/DmIOS.app
rm -rf "$A/_CodeSignature" "$A/embedded.mobileprovision" "$A/Extensions" "$A/PlugIns"   # 自签装机时扩展还要多占一个应用标识 | an extension would take one more App ID when sideloading

t "清单与版本信息（d3rm_pack.py 照它核对做全了没有）"
V=$(sed -n 's/^#define DMSH_CHAIN "\(.*\)"/\1/p' "$GD/dmsh_chain.h"); [ -n "$V" ] || die "游戏档案里没有 dmsh_chain.h：先跑 dm/gfx/tools/dmsh_chain.py --header"
{ echo "Frameworks/Guest.framework/";                       # 游戏程序动态库（guest_dylib.py 写出）| the game program dylib (written by guest_dylib.py)
  echo "romfs/";                                            # 游戏文件（RomFS；也可以放到 Documents/romfs，见 d3rm_pack.py）| the game files (RomFS; Documents/romfs is accepted too, see d3rm_pack.py)
  for m in main sdk; do for s in fixups gates params cuts obs; do echo "dm/$m.$s.tsv"; done; done
  echo "dm/main.cuts.tsv"; echo "dm/c1_full.tsv"; echo "dm/shader_map.tsv"; echo "dm/pso_manifest.tsv"
  echo "msl/b-$V/"; } > "$O/shell_manifest.txt"
cp "$O/shell_manifest.txt" "$A/dm/shell_manifest.txt"
printf 'PRODUCT=%s\nCHAIN=%s\nKIND=ios\nSHADER_SRC=\nSPIRV_CROSS=\n' "$(head -1 "$DM/PRODUCT")" "$V" > "$A/dm/shell_info.txt"
cp "$A/dm/shell_info.txt" "$O/shell_info.txt"

t "核对：壳里没有模块映像节，也没有游戏内容"
n=$(otool -l "$A/DmIOS" | grep -c -E 'sectname __dm.*x[01]|segname __DM.*W'); [ "$n" = 0 ] || die "壳的可执行文件里还有模块映像节 $n 个"
( cd "$A" && find . -type f | sort | while read -r f; do printf '%s\t%s\n' "$(stat -f %z "$f")" "$f"; done ) > "$O/shell_files.tsv"
( cd "$O" && rm -f "$OUT" && zip -qry "$(basename "$OUT")" Payload ) || die "zip"
t "壳：${OUT}（$(du -h "$OUT" | cut -f1)，$(wc -l < "$O/shell_files.tsv" | tr -d ' ') 个文件）；要补 $(grep -c . "$O/shell_manifest.txt") 项，清单 $O/shell_manifest.txt"
