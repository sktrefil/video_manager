"""Portable entry point. Uses only the adjacent private Python runtime."""
import json
import os
from pathlib import Path
import sys


ROOT=Path(__file__).resolve().parent.parent
for stream in (sys.stdout,sys.stderr):
    if stream is not None:stream.reconfigure(encoding='utf-8',errors='replace')
os.environ['PATH']=str(ROOT/'bin')+os.pathsep+os.environ.get('PATH','')
os.environ['QT_PLUGIN_PATH']=str(ROOT/'runtime/Lib/site-packages/PySide6/plugins')
os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)


def diagnose():
    from PySide6.QtWidgets import QApplication
    from video_manager.ui.batch_enhancer import BatchEnhancerWindow
    from video_manager.ui.watermark_preview import WatermarkPreview
    from video_manager.tools import diagnose as diagnose_tools
    import cv2,numpy,PIL,PySide6
    app=QApplication.instance() or QApplication([])
    window=BatchEnhancerWindow();app.processEvents();window.close()
    report=dict(executable=sys.executable,prefix=sys.prefix,import_paths=sys.path,
                versions=dict(opencv=cv2.__version__,numpy=numpy.__version__,pillow=PIL.__version__,qt=PySide6.__version__),
                gui_constructed=True,tools=diagnose_tools())
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    (logs/'diagnostics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Portable diagnostics passed',flush=True)
    return 0


if __name__=='__main__':
    if '--diagnose' in sys.argv:raise SystemExit(diagnose())
    from video_manager.ui.batch_enhancer import main
    raise SystemExit(main())
