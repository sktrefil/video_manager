"""One-clock combined comparison playback, with bounded frame memory."""
from pathlib import Path
import time

import cv2
from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtGui import QImage,QPixmap,QPainter,QPen,QColor
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSlider,QCheckBox

from ..errors import InputError


class ComparisonViewer(QWidget):
    positionChanged=Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.capture=None;self.frame_count=0;self.fps=0;self.position=0
        self._epoch=0;self._start_frame=0
        layout=QVBoxLayout(self)
        self.screen=QLabel('Open a comparison video');self.screen.setAlignment(Qt.AlignCenter)
        self.screen.setMinimumSize(480,250);layout.addWidget(self.screen)
        controls=QHBoxLayout();layout.addLayout(controls)
        self.play_button=QPushButton('Play');controls.addWidget(self.play_button)
        self.previous=QPushButton('−1 frame');controls.addWidget(self.previous)
        self.next=QPushButton('+1 frame');controls.addWidget(self.next)
        self.loop=QCheckBox('Loop comparison');controls.addWidget(self.loop)
        self.position_label=QLabel('No video');controls.addWidget(self.position_label)
        self.slider=QSlider(Qt.Horizontal);layout.addWidget(self.slider)
        self.timer=QTimer(self);self.timer.timeout.connect(self._tick)
        self.play_button.clicked.connect(self.toggle)
        self.previous.clicked.connect(lambda:self.step(-1));self.next.clicked.connect(lambda:self.step(1))
        self.slider.sliderMoved.connect(self.seek)

    def load(self,path):
        self.pause()
        if self.capture:self.capture.release()
        self.capture=cv2.VideoCapture(str(Path(path)))
        self.frame_count=int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT));self.fps=float(self.capture.get(cv2.CAP_PROP_FPS))
        if not self.capture.isOpened() or self.frame_count<1 or self.fps<=0:
            raise InputError(f'Cannot open comparison video: {path}')
        self.slider.setRange(0,self.frame_count-1)
        self.seek(0)

    def seek(self,frame):
        if not self.capture:return
        frame=max(0,min(self.frame_count-1,int(frame)))
        self.capture.set(cv2.CAP_PROP_POS_FRAMES,frame)
        ok,image=self.capture.read()
        if not ok:raise InputError(f'Cannot decode comparison frame {frame}')
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        height,width=rgb.shape[:2]
        qimage=QImage(rgb.data,width,height,rgb.strides[0],QImage.Format_RGB888).copy()
        self.screen.setPixmap(QPixmap.fromImage(qimage).scaled(self.screen.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.position=frame;self.slider.setValue(frame)
        self.position_label.setText(f'Frame {frame}/{self.frame_count-1} · {frame/self.fps:.3f} s')
        self.positionChanged.emit(frame)
        if self.timer.isActive():self._epoch=time.monotonic();self._start_frame=frame

    def step(self,delta):
        self.pause();self.seek(self.position+delta)

    def play(self):
        if not self.capture:return
        self._epoch=time.monotonic();self._start_frame=self.position
        self.timer.start(max(5,round(1000/self.fps)));self.play_button.setText('Pause')

    def pause(self):
        self.timer.stop();self.play_button.setText('Play')

    def toggle(self):
        self.pause() if self.timer.isActive() else self.play()

    def _tick(self):
        desired=self._start_frame+int((time.monotonic()-self._epoch)*self.fps)
        if desired>=self.frame_count:
            if self.loop.isChecked():
                self.seek(0);return
            self.seek(self.frame_count-1);self.pause();return
        if desired!=self.position:
            # Keep the real-time epoch while displaying the desired common-clock frame.
            epoch,start=self._epoch,self._start_frame
            self.seek(desired);self._epoch,self._start_frame=epoch,start

    def closeEvent(self,event):
        self.pause()
        if self.capture:self.capture.release()
        super().closeEvent(event)


class SpeedPlot(QWidget):
    """Simple continuous base-speed chart from the recorded timing model."""
    def __init__(self,parent=None):
        super().__init__(parent);self.model=None;self.setMinimumHeight(130)

    def set_model(self,model):
        self.model=model;self.update()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#f5f7fa'))
        painter.setPen(QColor('#263444'))
        painter.drawText(10,18,'Base speed curve (boundary/internal adjustments listed in report)')
        if not self.model:return
        m=self.model;end=m['output_last_display_seconds'];peak=m.get('terminal_speed',m['peak_speed']);protect=m['protect_seconds'];ramp=m['ramp_seconds']
        painter.setPen(QPen(QColor('#2767ac'),2))
        old=None
        for i in range(101):
            t=end*i/100;u=min(1,max(0,(t-protect)/ramp))
            speed=1+(peak-1)*(3*u*u-2*u*u*u) if m['compressed'] or m.get('stretched',False) else 1
            x=15+(self.width()-30)*i/100;y=self.height()-20-(self.height()-55)*speed/max(1,peak)
            if old:painter.drawLine(old[0],old[1],int(x),int(y))
            old=(int(x),int(y))
        painter.setPen(QColor('#263444'));painter.drawText(10,self.height()-3,f'0 → {end:.3f}s · terminal {peak:.2f}× · protect {protect:.2f}s')
