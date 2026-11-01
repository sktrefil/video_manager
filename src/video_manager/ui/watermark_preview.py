"""Inspect actual frames and annotate logo bounds before rendering a batch."""
from pathlib import Path
from types import SimpleNamespace

import cv2
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                              QLabel, QPushButton, QVBoxLayout, QWidget)

from ..watermark_crop import DEFAULT_REGIONS, apply_crop, plan_crop, validate_regions
from ..watermark import mark_mask, remove_mark


class FrameCanvas(QWidget):
    regionsChanged=Signal(object)

    def __init__(self,editable=False,parent=None):
        super().__init__(parent)
        self.editable=editable;self.frame=None;self.regions=[];self.crop=None;self.drag=None
        self.setMinimumSize(360,240)

    def set_frame(self,frame):
        self.frame=frame
        h,w=frame.shape[:2]
        self.image=QImage(frame.data,w,h,frame.strides[0],QImage.Format_RGB888).copy()
        self.update()

    def image_rect(self):
        if self.frame is None:return QRectF()
        h,w=self.frame.shape[:2]
        scale=min(self.width()/w,self.height()/h)
        return QRectF((self.width()-w*scale)/2,(self.height()-h*scale)/2,w*scale,h*scale)

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#202124'))
        if self.frame is None:return
        target=self.image_rect();painter.drawImage(target,self.image)
        def draw(region,color):
            x,y,w,h=region
            painter.setPen(QPen(QColor(color),2))
            painter.drawRect(QRectF(target.x()+x*target.width(),target.y()+y*target.height(),
                                   w*target.width(),h*target.height()))
        for region in self.regions:draw(region,'#ff6655')
        if self.crop is not None:
            h,w=self.frame.shape[:2];x,y,cw,ch=self.crop
            draw((x/w,y/h,cw/w,ch/h),'#44dd88')
        if self.drag:
            x0,y0,x1,y1=self.drag
            draw((min(x0,x1),min(y0,y1),abs(x1-x0),abs(y1-y0)),'#ffd166')

    def normalized_position(self,point):
        rect=self.image_rect()
        if rect.isEmpty():return None
        return (max(0,min(1,(point.x()-rect.x())/rect.width())),
                max(0,min(1,(point.y()-rect.y())/rect.height())))

    def mousePressEvent(self,event):
        if not self.editable or not self.image_rect().contains(event.position()):return
        x,y=self.normalized_position(event.position())
        if event.button()==Qt.RightButton:
            self.regions=[r for r in self.regions if not (r[0]<=x<=r[0]+r[2] and r[1]<=y<=r[1]+r[3])]
            self.regionsChanged.emit(self.regions);self.update()
        elif event.button()==Qt.LeftButton:self.drag=(x,y,x,y)

    def mouseMoveEvent(self,event):
        if self.drag:
            x,y=self.normalized_position(event.position())
            self.drag=(*self.drag[:2],x,y);self.update()

    def mouseReleaseEvent(self,event):
        if self.drag and event.button()==Qt.LeftButton:
            x0,y0,_,_=self.drag;x1,y1=self.normalized_position(event.position());self.drag=None
            rect=self.image_rect()
            if abs(x1-x0)*rect.width()>=4 and abs(y1-y0)*rect.height()>=4 and len(self.regions)<8:
                self.regions.append([min(x0,x1),min(y0,y1),abs(x1-x0),abs(y1-y0)])
                self.regionsChanged.emit(self.regions)
            self.update()


class WatermarkPreview(QDialog):
    def __init__(self,source,regions=None,parent=None,mode='crop'):
        super().__init__(parent)
        self.source=Path(source);self.frame=None;self.mode=mode
        self.setWindowTitle(f'워터마크 영역 미리보기 · {self.source.name}');self.resize(1150,620)
        layout=QVBoxLayout(self)
        if self.mode=='inpaint':
            note_text=('기본 빨간 영역은 두 로고의 예상 위치입니다. 실제 로고와 다르면 드래그로 영역을 다시 지정하세요.\n'
                       '영역 위에서 우클릭하면 삭제됩니다. 초록 테두리 크롭 없이 표시된 곳을 주변 픽셀로 메웁니다.')
        else:
            note_text=('기본 빨간 영역은 두 로고의 예상 위치입니다. 실제 로고와 다르면 모두 지운 뒤 로고를 드래그로 둘러싸세요.\n'
                       '영역 위에서 우클릭하면 삭제됩니다. 초록 테두리는 남길 화면입니다. 자동 로고 검출 기능은 아닙니다.')
        note=QLabel(note_text)
        note.setWordWrap(True);layout.addWidget(note)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        toolbar.addWidget(QLabel('확인할 장면'))
        self.position=QComboBox()
        for label,value in [('앞부분',.05),('중간',.5),('끝부분',.95)]:self.position.addItem(label,value)
        toolbar.addWidget(self.position)
        clear=QPushButton('영역 모두 지우기');clear.clicked.connect(lambda:self.set_regions([]));toolbar.addWidget(clear)
        reset=QPushButton('두 로고 기본 영역');reset.clicked.connect(lambda:self.set_regions(DEFAULT_REGIONS));toolbar.addWidget(reset)
        toolbar.addStretch()
        columns=QHBoxLayout();layout.addLayout(columns,1)
        self.original=FrameCanvas(editable=True);self.result=FrameCanvas()
        for name,widget in [('원본 · 로고 영역 지정',self.original),('결과 예상 · 화면 비율 유지',self.result)]:
            column=QVBoxLayout();column.addWidget(QLabel(name));column.addWidget(widget,1);columns.addLayout(column,1)
        self.summary=QLabel();self.summary.setWordWrap(True);layout.addWidget(self.summary)
        footer=('앞·중간·끝의 로고 위치를 확인하세요. 결과 영상의 해상도와 자막 위치는 유지됩니다.'
                if self.mode=='inpaint' else
                '앞·중간·끝의 로고 위치를 확인하세요. 흔들림 보정을 함께 켜면 최종 크롭이 더 커질 수 있습니다.')
        layout.addWidget(QLabel(footer))
        self.buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('이 파일에 적용')
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
        self.original.regions=validate_regions(DEFAULT_REGIONS if regions is None else regions)
        self.custom_regions=(regions is not None and validate_regions(regions)!=validate_regions(DEFAULT_REGIONS))
        self.original.regionsChanged.connect(self.regions_changed)
        self.position.currentIndexChanged.connect(self.load_frame)
        self.load_frame()

    @property
    def regions(self):return self.original.regions

    def set_regions(self,regions):
        self.original.regions=validate_regions(regions)
        self.custom_regions=self.original.regions!=validate_regions(DEFAULT_REGIONS)
        self.refresh_result()

    def regions_changed(self,_):
        self.custom_regions=self.original.regions!=validate_regions(DEFAULT_REGIONS)
        self.refresh_result()

    def load_frame(self):
        capture=cv2.VideoCapture(str(self.source))
        try:
            if not capture.isOpened():raise ValueError('영상을 열 수 없습니다.')
            count=capture.get(cv2.CAP_PROP_FRAME_COUNT)
            capture.set(cv2.CAP_PROP_POS_FRAMES,max(0,int((count-1)*self.position.currentData())))
            ok,frame=capture.read()
            if not ok:raise ValueError('선택한 장면을 읽을 수 없습니다.')
            sar_num=capture.get(cv2.CAP_PROP_SAR_NUM);sar_den=capture.get(cv2.CAP_PROP_SAR_DEN)
            sar=sar_num/sar_den if sar_num>0 and sar_den>0 else 1
            h,w=frame.shape[:2];dw=max(2,round(w*sar/2)*2);dh=max(2,round(h/2)*2)
            if (w,h)!=(dw,dh):frame=cv2.resize(frame,(dw,dh))
            self.frame=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            self.original.set_frame(self.frame);self.refresh_result()
        except Exception as exc:
            self.summary.setText(str(exc));self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        finally:capture.release()

    def refresh_result(self):
        if self.frame is None:return
        try:
            h,w=self.frame.shape[:2]
            if self.mode=='inpaint':
                clip=SimpleNamespace(width=w,height=h,sample_aspect_ratio=1)
                options={'profile':'both_inpaint'}
                if self.custom_regions:options['regions']=self.regions
                mask,rectangle=mark_mask(clip,w,h,options)
                self.original.crop=None;self.original.update()
                self.result.set_frame(remove_mark(self.frame,mask))
                self.summary.setText(f'지정 영역 {len(self.regions) if self.custom_regions else 2}개 · 화면 크롭 없음 · 제거 마스크 범위 {rectangle["width"]}×{rectangle["height"]} px')
            else:
                plan=plan_crop(w,h,self.regions)
                self.original.crop=plan['rect'];self.original.update()
                self.result.set_frame(apply_crop(self.frame,plan))
                loss=(1-plan['retained_area_fraction'])*100
                self.summary.setText(f'지정 영역 {len(self.regions)}개 · 화면 면적 손실 {loss:.1f}% · 확대 {plan["zoom"]:.3f}배'
                                     + (' · 화면 손실이 큽니다. 로고 영역을 더 좁혀보세요.' if loss>40 else ''))
            self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        except Exception as exc:
            self.summary.setText(str(exc));self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
