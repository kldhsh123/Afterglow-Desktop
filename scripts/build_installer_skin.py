"""Compile the original x86 NSIS skin; never execute a generated Windows file.

Uses existing SDK headers and tiny import libraries generated from public Win32
exports. The DLL has no C runtime, installer actions, downloads or account data.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = {
    'kernel32': {'GetProcessHeap':0, 'HeapAlloc':12, 'HeapFree':12, 'MulDiv':12},
    'user32': {'GetWindowTextW':12, 'SendMessageW':16, 'IsWindowEnabled':4, 'GetFocus':0,
        'FillRect':12, 'GetClientRect':8, 'TrackMouseEvent':4, 'InvalidateRect':12,
        'BeginPaint':8, 'EndPaint':8, 'GetDC':4, 'ReleaseDC':8, 'GetWindowLongW':8,
        'SetWindowLongW':12, 'SetWindowPos':28, 'SystemParametersInfoW':16,
        'RedrawWindow':16, 'InflateRect':12, 'DrawTextW':20, 'EnumChildWindows':12,
        'MapDialogRect':8},
    'gdi32': {'CreateSolidBrush':4, 'CreatePen':12, 'SelectObject':8, 'RoundRect':28,
        'DeleteObject':4, 'SetBkMode':8, 'SetTextColor':8, 'SetBkColor':8, 'MoveToEx':16,
        'LineTo':12, 'GetStockObject':4, 'CreateCompatibleDC':4, 'CreateCompatibleBitmap':12,
        'BitBlt':36, 'DeleteDC':4, 'GetDeviceCaps':8},
    'comctl32': {'SetWindowSubclass':16, 'GetWindowSubclass':16, 'RemoveWindowSubclass':12, 'DefSubclassProc':16},
    'uxtheme': {'SetWindowTheme':12},
}


def build():
    toolroot = ROOT / '开发缓存/工具链/llvm/usr/lib/llvm-18/bin'
    def tool(name): return shutil.which(name) or str(toolroot / name)
    sdk = Path(os.environ.get('XWIN_CACHE_DIR', str(Path.home()/'.cache/afterglow-desktop/xwin-cache'))) / 'xwin/sdk/include'
    if not (sdk/'um/Windows.h').is_file() and not (sdk/'um/windows.h').is_file():
        raise ValueError('Prepare the Windows SDK before rebuilding installer controls')
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = str(ROOT/'开发缓存/工具链/llvm/usr/lib/x86_64-linux-gnu') + os.pathsep + env.get('LD_LIBRARY_PATH','')
    output = ROOT / 'src-tauri/icons/installer-skin.dll'
    with tempfile.TemporaryDirectory(prefix='afterglow-skin-') as directory:
        folder = Path(directory)
        libraries = []
        for dll, functions in IMPORTS.items():
            definition=folder/(dll+'.def'); library=folder/(dll+'.lib')
            # The Windows compatibility comctl32 exports GetWindowSubclass by
            # ordinal 411 only. Importing it by name makes LoadLibrary fail
            # with ERROR_PROC_NOT_FOUND (127), leaving controls unstyled.
            definition.write_text('LIBRARY '+dll+'.dll\nEXPORTS\n'+''.join(
                f'{name}@{size} @411 NONAME\n' if dll == 'comctl32' and name == 'GetWindowSubclass'
                else f'{name}@{size}\n' for name,size in functions.items()))
            subprocess.run([tool('llvm-dlltool'),'-m','i386','-k','-d',str(definition),'-l',str(library)],check=True,env=env)
            libraries.append(str(library))
        obj=folder/'skin.obj'
        subprocess.run([tool('clang-cl'),'--target=i686-pc-windows-msvc','/c','/O2','/GS-','/Zl','/W4',
            '/clang:-ffreestanding','/clang:-fno-builtin',f'/imsvc{sdk.parent.parent / "crt/include"}',*[f'/imsvc{sdk/name}' for name in ('um','shared','ucrt')],
            '/Fo'+str(obj),str(ROOT/'scripts/installer/skin.c')],check=True,env=env)
        exports=folder/'exports.def';exports.write_text('EXPORTS\nAttach=_Attach@8\nRefresh=_Refresh@4\nDetach=_Detach@4\n')
        subprocess.run([tool('lld-link'),'/dll','/noentry','/nodefaultlib','/machine:x86','/timestamp:0',
            '/def:'+str(exports),'/out:'+str(output),'/implib:'+str(folder/'skin.lib'),str(obj),*libraries],check=True,env=env)
    print(output)


if __name__=='__main__': build()
