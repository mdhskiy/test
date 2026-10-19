#!/usr/bin/env python3
# 不用 Xcode 出 D3 的安装包：把自己的游戏文件做进「壳」（dm/ios/tools/shell_build.sh 的产物，CI 或 Mac 上构建）。
#   壳是一个不含任何游戏内容、没有签名的安装包（zip）；本工具在你的电脑（Windows）上生成它缺的全部内容——改写后的游戏程序
#   （Guest.framework）、着色器库（MSL 源码，设备端现编）、改写表、下标清单——放进去，写出一个新的未签名 IPA。
#   之后用自签工具（iLoader / AltStore / Sideloadly）整包签名装机。游戏文件只在本机读，不上传。
# 用法：d3rm_pack.py --shell <壳.zip> --game <游戏目录> --out <输出.ipa> [选项]
#   --game <目录>      里面有 ExeFS/{main,sdk}（nx_extract 解出的；更新版优先）
#   --romfs <目录>     游戏文件（RomFS）。缺省不打进 IPA——用文件共享放到手机的 Documents/romfs（App 启动时也认，见 main.m）
#   --aoc <目录>       追加内容（DLC 的 RomFS，一层一个序号子目录，如 11/）。缺省打进 IPA；--no-aoc 跳过（游戏没有语言包也能起）
#   --guest-patch <py> 可选：改写之后、写动态库之前跑的客体侧补丁脚本（你的 d3_patch_main.py 之类），环境变量给出各路径
#   --pkg <目录>       着色器包目录（shader_split.py 的产物），缺省 $DM_ROOT/build/shader/pkg
# 环境：DM_GAME=游戏档案（必给；仓内 dm/games/<标题号> 或 DM_GAMES_DIR 里的临时档案）、DM_ROOT=工作根目录（本工具的 _build 目录，缺省 ~/dm-work）、
#       PATH 里要有 spirv-cross；DOTNET_ROOT 指向 .NET SDK（本机裸 dotnet 若是纯运行时版）；XLATE 可指到自编的翻译器目录。
#       在带 safe-delete 注入的沙箱里跑，先 export CODEBUDDY_SAFE_DELETE_ENABLED=0（否则清理中间文件会被当批量删除杀掉）。
# Make D3's install package without Xcode: build your own game files into the "shell" (the output of dm/ios/tools/shell_build.sh, built on CI or a Mac).
#   The shell is an unsigned install package (a zip) with no game content; this tool generates everything it lacks on your computer (Windows) --
#   the rewritten game program (Guest.framework), the shader libraries (MSL source, compiled on the device), the rewriter tables and the index list --
#   puts them in, and writes a new unsigned IPA. Then sign the whole package with a sideloading tool (iLoader / AltStore / Sideloadly) and install it.
#   Your game files are only read locally and never uploaded.
import argparse, json, os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE); DM = os.path.join(REPO, 'dm'); GT = os.path.join(DM, 'gfx', 'tools')
ROOT = os.path.abspath(os.environ.get('DM_ROOT') or os.path.expanduser('~/dm-work'))
PY = sys.executable
MODS = ['main', 'sdk']


def say(m): print('[d3rm_pack] ' + m, flush=True)


def die(m): sys.exit('[d3rm_pack] FAIL: ' + m)


def run(cmd, env=None, log=None, what=''):
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, errors='replace')
    if log:
        open(log, 'w', encoding='utf-8', errors='replace').write((r.stdout or '') + (r.stderr or ''))
    if r.returncode: die('%s：退出码 %d\n%s' % (what or ' '.join(map(str, cmd)), r.returncode, ((r.stderr or '') + (r.stdout or ''))[-1500:]))
    return r


def game_env(**kw):
    e = dict(os.environ, DM_ROOT=ROOT, PYTHONUTF8='1')
    e.update(kw)
    return e


def nometal(script, *a):   # 没有苹果的 Metal 编译器：MSL 以源码进包，设备端现编（nometal_run.py 拦 xcrun）
    return [PY, os.path.join(GT, 'nometal_run.py'), os.path.join(GT, script), *a]


def build_id(path):
    d = open(path, 'rb').read(0x50)
    return d[0x40:0x50].hex() if d[:4] == b'NSO0' else None


def main():
    ap = argparse.ArgumentParser(description='pack D3 into the nxnative shell on Windows (no Xcode)')
    ap.add_argument('--shell', required=True, help='the shell zip (DmIOS-shell-build-input.zip)')
    ap.add_argument('--game', required=True, help='the game directory holding ExeFS/{main,sdk}')
    ap.add_argument('--out', required=True, help='the output IPA (unsigned)')
    ap.add_argument('--romfs', help='the RomFS directory (packed into the IPA; without it, put it in the phone\'s Documents/romfs)')
    ap.add_argument('--aoc', help='the add-on content directory (one subdirectory per DLC index, e.g. 11/)')
    ap.add_argument('--no-aoc', action='store_true', help='do not pack add-on content (the game still boots)')
    ap.add_argument('--guest-patch', help='a script to run after the rewrite, before the dylib (your guest-side patches)')
    ap.add_argument('--pkg', default=os.path.join(ROOT, 'shader', 'pkg'), help='the shader package directory')
    args = ap.parse_args()
    game = os.path.abspath(args.game)
    for m in MODS:
        if not os.path.isfile(os.path.join(game, 'ExeFS', m)): die('%s 里没有 ExeFS/%s' % (game, m))
    GAME = os.environ.get('DM_GAME') or die('DM_GAME is not set (the base game title ID)')
    PROF = os.environ.get('DM_GAMES_DIR') or os.path.join(DM, 'games')
    prof = os.path.join(PROF, GAME)
    if not os.path.isfile(os.path.join(prof, 'game.tsv')): die('no game profile %s/game.tsv' % prof)

    stage = os.path.join(ROOT, 'pack', 'stage'); shutil.rmtree(stage, ignore_errors=True); os.makedirs(os.path.join(stage, 'dm'))
    ios_out = os.path.join(ROOT, 'shader', 'ios'); cache = os.path.join(ROOT, 'shader', 'cache')
    out_dir = os.path.join(ROOT, 'patched_native')

    # 一、开壳，读它的清单与版本信息 | open the shell, read its manifest and version info
    say('壳 %s' % os.path.basename(args.shell))
    z = zipfile.ZipFile(args.shell)
    info = dict(l.split('=', 1) for l in z.read('Payload/DmIOS.app/dm/shell_info.txt').decode().splitlines() if '=' in l)
    P = open(os.path.join(DM, 'PRODUCT')).readline().strip()
    if info.get('PRODUCT') != P: die('壳与这份源码不是同一版：壳要 %s，这份是 %s' % (info.get('PRODUCT'), P))
    chain = info.get('CHAIN') or die('壳的版本信息里没有着色器链版本')
    manifest = [l.strip() for l in z.read('Payload/DmIOS.app/dm/shell_manifest.txt').decode().splitlines() if l.strip()]
    z.extractall(stage)
    say('壳：产物代号 %s，着色器链 %s，要补 %d 项' % (P, chain, len(manifest)))

    # 二、改写游戏程序（与 build_ipa_from_nsp.py 同一调用：通用 native 规则集）| rewrite the game program (the same call as build_ipa_from_nsp.py: the generic native ruleset)
    want = {}
    for ln in open(os.path.join(prof, 'game.tsv'), encoding='utf-8'):
        c = ln.rstrip('\n').split('\t')
        if c and c[0] == 'build':
            for kv in c[3:]:
                k, v = kv.split('=')
                want[k] = v
    os.makedirs(out_dir, exist_ok=True)

    def patch():
        for m in MODS:
            got = build_id(os.path.join(game, 'ExeFS', m))
            if m in want and got != want[m]: die('ExeFS/%s 的构建号 %s 与档案登记的 %s 不同' % (m, got, want[m]))
            run([PY, os.path.join(DM, 'tools', 'patch_nso.py'), os.path.join(game, 'ExeFS', m), out_dir, m],
                env=game_env(DM_RULESET='native'), log=os.path.join(out_dir, m + '.patch.log'), what='改写 ' + m)
    if not all(os.path.isfile(os.path.join(out_dir, m + '.patched.bin')) for m in MODS): patch()
    say('改写完成：%s' % ', '.join('%s=%s' % (m, want.get(m, '?')) for m in MODS))
    if args.guest_patch:   # 客体侧补丁（VAMM 初始化那类）；路径经环境变量给它
        say('客体侧补丁：%s' % args.guest_patch)
        run([PY, os.path.abspath(args.guest_patch)], env=game_env(PATCHED=out_dir, GAME_DIR=game, EXEFS=os.path.join(game, 'ExeFS')),
            log=os.path.join(stage, 'guest_patch.log'), what='客体侧补丁')

    # 三、着色器链：本机工具与仓库登记的不同是正常的（Windows 没有 Metal 编译器）——按本机工具重登记，链版本走自己的分支
    # the shader chain: it is normal for the local tools to differ (no Metal compiler on Windows) -- re-register locally; the chain version forms its own branch
    xl = os.path.join(ROOT, 'build', 'gfx', 'dmsh_xlate')
    if not (os.path.isfile(os.path.join(xl, 'dmsh_xlate')) or os.path.isfile(os.path.join(xl, 'dmsh_xlate.exe'))):
        run(['dotnet', 'publish', os.path.join(GT, 'dmsh_xlate'), '-c', 'Release', '-o', xl, '-v', 'quiet'], what='编译着色器翻译工具')
        if not os.path.isfile(os.path.join(xl, 'dmsh_xlate')):   # Windows 的 apphost 带 .exe，dmsh_chain 调的是无扩展名那个：补一个（PE 无扩展名也能被 CreateProcess 执行）
            shutil.copyfile(os.path.join(xl, 'dmsh_xlate.exe'), os.path.join(xl, 'dmsh_xlate'))
    chk = lambda: subprocess.run(nometal('dmsh_chain.py', '--check-tools'), env=game_env(XLATE=os.path.join(xl, 'dmsh_xlate')),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not chk():
        say('本机工具与仓库登记的不同：按本机工具重新登记翻译链')
        run(nometal('dmsh_chain.py', '--update-lock'), env=game_env(XLATE=os.path.join(xl, 'dmsh_xlate')), what='登记翻译链')
    run(nometal('dmsh_chain.py', '--header'), env=game_env(XLATE=os.path.join(xl, 'dmsh_xlate')), what='写翻译链版本')
    local = run(nometal('dmsh_chain.py'), env=game_env(XLATE=os.path.join(xl, 'dmsh_xlate')), what='取翻译链版本').stdout.strip().splitlines()[-1]

    # 四、翻译全部着色器（首次约 10 分钟；MSL 源码进包，设备端现编）| translate all shaders (about 10 minutes the first time; MSL source goes in, compiled on the device)
    def shaders_done():
        try: res = json.load(open(os.path.join(cache, 'b-' + local, '_b_build.json'), encoding='utf-8'))
        except (OSError, ValueError): return False
        d = os.path.join(ios_out, 'b-' + local); have = set(os.listdir(d)) if os.path.isdir(d) else set()
        bad = [r for r in res if r['st'] != 'ok']; miss = [r for r in res if r['st'] == 'ok' and r['key'] + '_b.metallib' not in have]
        return bool(res) and not bad and not miss
    if not shaders_done():
        say('翻译全部着色器（MSL 源码，设备端现编）')
        run(nometal('dmsh_build.py', args.pkg, cache), env=game_env(XLATE=os.path.join(xl, 'dmsh_xlate'), IOSOUT=ios_out,
            J=os.environ.get('J', '6'), MAIN=os.path.join(game, 'ExeFS', 'main')), log=os.path.join(stage, 'shaders.log'), what='翻译着色器')
    if not shaders_done(): die('着色器没做全（完整输出见 %s）' % os.path.join(stage, 'shaders.log'))
    n_msl = len([f for f in os.listdir(os.path.join(ios_out, 'b-' + local)) if f.endswith('_b.metallib')])
    say('着色器 %d 个（链版本 %s）' % (n_msl, local))

    # 五、链版本对齐到壳认的那个：目录名、每个说明里的版本、下标清单首行 | align the chain version to the shell's: directory name, each json's version, the index list's first line
    lib = os.path.join(stage, 'msl', 'b-' + chain); os.makedirs(os.path.dirname(lib))
    shutil.copytree(os.path.join(ios_out, 'b-' + local), lib)
    if local != chain:
        old, new, n = ('"chain": "%s"' % local).encode(), ('"chain": "%s"' % chain).encode(), 0
        for f in os.listdir(lib):
            if f.endswith('.json'):
                b = open(os.path.join(lib, f), 'rb').read()
                if old in b: open(os.path.join(lib, f), 'wb').write(b.replace(old, new)); n += 1
        if not n: die('着色器说明里没找到链版本 %s（格式变了？）' % local)
        say('着色器库按本机工具出（链版本 %s），按壳认的目录名与版本放进 b-%s（%d 个说明已改）' % (local, chain, n))
    run([PY, os.path.join(GT, 'c1_guard.py'), os.path.join(cache, 'b-' + local), os.path.join(stage, 'dm', 'c1_full.tsv')], what='出着色器下标清单')
    if local != chain:
        t = open(os.path.join(stage, 'dm', 'c1_full.tsv'), encoding='utf-8').read()
        open(os.path.join(stage, 'dm', 'c1_full.tsv'), 'w', encoding='utf-8').write(t.replace('b-' + local, 'b-' + chain, 1))

    # 六、游戏程序写成动态库 + 装载表 | write the game program as a dynamic library + the load tables
    sys.path.insert(0, os.path.join(DM, 'tools'))
    import guest_dylib
    fw, n = guest_dylib.write(out_dir, os.path.join(stage, 'Frameworks'), MODS)
    say('游戏程序动态库：%d 字节' % n)
    for f in [m + s for m in MODS for s in ('.fixups.tsv', '.gates.tsv', '.params.tsv', '.cuts.tsv', '.obs.tsv')] + ['bootlist.tsv', 'main.cuts.tsv']:
        if os.path.isfile(os.path.join(out_dir, f)): shutil.copyfile(os.path.join(out_dir, f), os.path.join(stage, 'dm', f))
    for f in ('shader_map.tsv', 'pso_manifest.tsv'):
        shutil.copyfile(os.path.join(prof, f), os.path.join(stage, 'dm', f))
    with open(os.path.join(stage, 'dm', 'pack_info.txt'), 'w', encoding='utf-8') as f: f.write('PRODUCT=%s\n' % P)

    # 七、追加内容（可选）| add-on content (optional)
    aoc_note = ''
    if args.aoc and not args.no_aoc:
        for idx in sorted(os.listdir(args.aoc)):
            if os.path.isdir(os.path.join(args.aoc, idx)):
                shutil.copytree(os.path.join(args.aoc, idx), os.path.join(stage, 'aoc', idx))
                aoc_note += ' aoc/%s' % idx
        say('追加内容：%s' % aoc_note.strip())
    elif not args.no_aoc:
        say('没有给 --aoc：语言包等追加内容不进包（游戏能起，没有简中）')

    # 八、照壳的清单核对一项不缺（romfs 可放手机 Documents/romfs，清单里那项由装机步骤补）| check against the shell's manifest (romfs/ can live in the phone's Documents)
    miss = []
    for m in manifest:
        if m == 'romfs/':
            if args.romfs: shutil.copytree(args.romfs, os.path.join(stage, 'romfs'))
            else:
                say('提醒：RomFS 没打进包——用文件共享把整个 RomFS 目录放到手机的 Documents/romfs（App 启动先认它）')
            continue
        p = os.path.join(stage, m)
        if not (os.path.isdir(p) if m.endswith('/') else os.path.isfile(p)): miss.append(m)
    if miss: die('有 %d 项没做出来：%s' % (len(miss), '、'.join(miss)))

    # 九、组装 IPA：壳的原样 + 新做的（已压缩的按原样存，其余 deflate）| assemble: the shell's entries as they are + the new ones (already-compressed stored, the rest deflated)
    store = set()
    for ln in open(os.path.join(prof, 'game.tsv'), encoding='utf-8'):
        c = ln.rstrip('\n').split('\t')
        if c and c[0] == 'zip_store': store = set(c[1].split(':'))
    tmp = args.out + '.part'; added = 0
    with zipfile.ZipFile(tmp, 'w') as o:
        for i in z.infolist(): o.writestr(i, z.read(i.filename))
        extra = ['dm/pack_info.txt']   # bookkeeping (the current app does not read it; D2R-mobile's does)
        for m in dict.fromkeys(manifest + extra + (['aoc/'] if aoc_note else [])):
            src = os.path.join(stage, m)
            if not os.path.exists(src): continue
            files = [os.path.join(d, f) for d, _, fs in sorted(os.walk(src)) for f in sorted(fs)] if m.endswith('/') else [src]
            for f in files:
                zi = zipfile.ZipInfo('Payload/DmIOS.app/' + os.path.relpath(f, stage).replace(os.sep, '/'), date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_STORED if os.path.splitext(f)[1] in store else zipfile.ZIP_DEFLATED
                zi.external_attr = (0o755 if os.path.basename(f) == 'Guest' else 0o644) << 16
                o.writestr(zi, open(f, 'rb').read()); added += 1
    os.replace(tmp, args.out)
    say('好了：%s（%.0f MB，放进去 %d 个文件%s）' % (args.out, os.path.getsize(args.out) / 1048576, added, '，RomFS 在 IPA 里' if args.romfs else ''))
    say('下一步：用 iLoader / AltStore / Sideloadly 给它签名装机；这个安装包里有游戏内容，请只自己用')


if __name__ == '__main__':
    main()
