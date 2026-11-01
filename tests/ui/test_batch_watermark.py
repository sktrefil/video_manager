from fractions import Fraction
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from video_manager.batch_enhance import output_path,save_regions
from video_manager.render import Encoder
from video_manager.ui.batch_enhancer import BatchEnhancerWindow
from video_manager.ui.watermark_preview import WatermarkPreview


class BatchWatermarkUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def make_video(self,root):
        source=root/'sample.mp4';encoder=Encoder(source,320,180,Fraction(8))
        try:
            for i in range(8):
                frame=np.full((180,320,3),30+i,np.uint8);frame[163:172,250:313]=255
                encoder.write(frame.tobytes())
        finally:encoder.close()
        return source

    def test_drag_regions_and_check_multiple_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=self.make_video(Path(tmp));dialog=WatermarkPreview(source)
            try:
                dialog.show();self.app.processEvents();dialog.set_regions([])
                canvas=dialog.original;rect=canvas.image_rect()
                first=QPoint(round(rect.x()+rect.width()*.77),round(rect.y()+rect.height()*.90))
                last=QPoint(round(rect.x()+rect.width()*.98),round(rect.y()+rect.height()*.97))
                QTest.mousePress(canvas,Qt.LeftButton,pos=first)
                QTest.mouseMove(canvas,last);QTest.mouseRelease(canvas,Qt.LeftButton,pos=last)
                self.assertEqual(len(dialog.regions),1)
                self.assertIn('화면 면적 손실',dialog.summary.text())
                region=list(dialog.regions[0])
                for index in (1,2):
                    dialog.position.setCurrentIndex(index);self.app.processEvents()
                    self.assertEqual(dialog.regions[0],region)
                    self.assertIsNotNone(dialog.result.frame)
                middle=QPoint((first.x()+last.x())//2,(first.y()+last.y())//2)
                QTest.mouseClick(canvas,Qt.RightButton,pos=middle)
                self.assertEqual(dialog.regions,[])
            finally:dialog.close();self.app.processEvents()

    def test_batch_completion_and_changed_region_requires_reprocessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=self.make_video(root);window=BatchEnhancerWindow()
            try:
                window.folder_label.setText(str(root));window.scan()
                self.assertEqual(window.table.rowCount(),1)
                window.start_batch();deadline=time.monotonic()+30
                while window.worker is not None and time.monotonic()<deadline:QTest.qWait(20)
                self.assertIsNone(window.worker)
                self.assertEqual(window.table.item(0,1).text(),'완료')
                window.scan();self.assertEqual(window.table.item(0,1).text(),'완료')
                save_regions(output_path(source,root),[[.77,.90,.21,.07]])
                window.scan();self.assertEqual(window.table.item(0,1).text(),'재처리 필요')
            finally:
                if window.worker is not None:
                    window.worker.cancel();window.worker.wait(30000);self.app.processEvents()
                window.close();self.app.processEvents()


if __name__=='__main__':unittest.main()
