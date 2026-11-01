"""Offline Windows x64 distribution using the locally installed C# compiler."""
import argparse
import compileall
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[2]
IGNORE=shutil.ignore_patterns('__pycache__','*.pyc','tests','test','*.whl','*.lib','*.pdb')


def copy_tree(source,target):
    shutil.copytree(source,target,dirs_exist_ok=True,ignore=IGNORE)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'dist/VideoEnhancer')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to((ROOT/'dist').resolve()):raise ValueError('Build output must be inside this workspace/dist')
    if os.name!='nt':raise RuntimeError('This build requires Windows')
    base=Path(sys.base_prefix);packages=Path(sys.prefix)/'Lib/site-packages'
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise FileNotFoundError(compiler)
    runtime=out/'runtime';site=runtime/'Lib/site-packages';app=out/'app';bin_dir=out/'bin'
    for path in (runtime,site,app,bin_dir,out/'licenses'):path.mkdir(parents=True,exist_ok=True)
    print('Copy Python runtime',flush=True)
    for path in base.iterdir():
        if path.suffix=='.dll' or path.name in ('python.exe','pythonw.exe','LICENSE.txt'):
            shutil.copy2(path,runtime/path.name)
    copy_tree(base/'DLLs',runtime/'DLLs')
    shutil.copytree(base/'Lib',runtime/'Lib',dirs_exist_ok=True,
                   ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc','test','tests','idlelib','tkinter','turtledemo','ensurepip'))
    (runtime/'python311._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n../app\nimport site\n',encoding='utf-8')
    print('Copy image and Qt libraries',flush=True)
    for name in ('numpy','numpy.libs','cv2','PIL','shiboken6'):
        copy_tree(packages/name,site/name)
    if (packages/'pillow.libs').exists():copy_tree(packages/'pillow.libs',site/'pillow.libs')
    qt=packages/'PySide6';qt_out=site/'PySide6';qt_out.mkdir(exist_ok=True)
    dlls={'Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','Qt6OpenGL.dll','Qt6Svg.dll','Qt6Network.dll',
          'pyside6.abi3.dll','opengl32sw.dll','concrt140.dll'}
    for path in qt.iterdir():
        if path.is_file() and (path.suffix=='.py' or path.name in dlls or path.name.startswith(('msvcp','vcruntime','icu'))
                              or path.name in ('QtCore.pyd','QtGui.pyd','QtWidgets.pyd')):
            shutil.copy2(path,qt_out/path.name)
    copy_tree(qt/'support',qt_out/'support')
    for directory in ('platforms','styles','imageformats','iconengines'):
        if (qt/'plugins'/directory).is_dir():copy_tree(qt/'plugins'/directory,qt_out/'plugins'/directory)
    for metadata in packages.glob('*.dist-info'):
        if metadata.name.lower().startswith(('numpy-','opencv_','pillow-','pyside6','shiboken6-')):
            copy_tree(metadata,site/metadata.name)
    print('Copy application and FFmpeg',flush=True)
    copy_tree(ROOT/'src/video_manager',app/'video_manager')
    shutil.copy2(Path(__file__).with_name('launch.py'),app/'launch.py')
    tool_paths={}
    for name in ('ffmpeg','ffprobe'):
        located=shutil.which(name)
        if not located:raise FileNotFoundError(name)
        tool=Path(located);shutil.copy2(tool,bin_dir/(name+'.exe'));tool_paths[name]=str(tool)
        for license_file in tool.parent.parent.glob('*'):
            if license_file.is_file() and license_file.name.lower().startswith(('license','copying','readme')):
                shutil.copy2(license_file,out/'licenses'/('ffmpeg-'+license_file.name))
    shutil.copy2(base/'LICENSE.txt',out/'licenses/Python-LICENSE.txt')
    compileall.compile_dir(app,quiet=1)
    print('Compile Windows executable launcher',flush=True)
    subprocess.run([str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
                    '/reference:System.Windows.Forms.dll','/out:'+str(out/'VideoEnhancer.exe'),
                    str(Path(__file__).with_name('VideoEnhancer.cs'))],check=True)
    (out/'README.txt').write_text(
        'Video Enhancer (Windows x64)\n\nVideoEnhancer.exe를 실행하세요. Python과 FFmpeg를 별도로 설치할 필요가 없습니다.\n'
        'exe 파일만 옮기지 말고 VideoEnhancer 폴더 전체를 함께 보관하거나 복사하세요.\n'
        '폴더 선택 → 필요한 효과 선택 → 미완료 파일 처리 순서로 사용합니다.\n'
        '워터마크 영역 미리보기에서 실제 로고 위치를 조정할 수 있습니다.\n'
        '결과는 입력 폴더의 video_manager_output에 저장됩니다.\n'
        '문제가 있으면 logs/launcher.log를 확인하세요. VideoEnhancer.exe --diagnose로 실행 환경을 점검할 수 있습니다.\n',encoding='utf-8-sig')
    (out/'build_manifest.json').write_text(json.dumps(dict(python=sys.version,source=str(ROOT),
         kind='native C# launcher with isolated Python runtime',tools=tool_paths),indent=2),encoding='utf-8')
    print(str(out/'VideoEnhancer.exe'),flush=True)


if __name__=='__main__':main()
