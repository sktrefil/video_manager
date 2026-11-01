"""Standalone desktop app for processing videos selected by folder or file."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..batch_enhance import (OUTPUT_FOLDER, VIDEO_EXTENSIONS, discover_videos, output_path, process_video,
                            is_completed,load_regions,save_regions)
from ..watermark_crop import DEFAULT_REGIONS


class BatchWorker(QThread):
    item_status=Signal(str,str)
    progress=Signal(int,int,str)
    finished_batch=Signal(int,int,bool)

    def __init__(self,files,folder,options,interpolate,parent=None,per_source_folder=False):
        super().__init__(parent)
        self.files=list(files);self.folder=Path(folder);self.options=options;self.interpolate=interpolate
        self.per_source_folder=per_source_folder
        self.cancel_requested=False

    def cancel(self):self.cancel_requested=True

    def run(self):
        completed=failed=0
        for index,source in enumerate(self.files,1):
            if self.cancel_requested:break
            destination=output_path(source,source.parent if self.per_source_folder else self.folder)
            options=self.options[str(source)]
            if is_completed(source,destination,options):
                completed+=1;self.item_status.emit(str(source),'완료')
                self.progress.emit(index,len(self.files),source.name);continue
            self.item_status.emit(str(source),'처리 중')
            self.progress.emit(index-1,len(self.files),f'{source.name}: 처리 중')
            try:
                process_video(source,destination,options,interpolate=self.interpolate,
                    progress=lambda message:self.progress.emit(index-1,len(self.files),f'{source.name}: {message}'))
                completed+=1;self.item_status.emit(str(source),'완료')
            except Exception as exc:
                failed+=1;self.item_status.emit(str(source),f'오류: {exc}')
            self.progress.emit(completed+failed,len(self.files),source.name)
        self.finished_batch.emit(completed,failed,self.cancel_requested)


def _table_item(text,tooltip=None):
    item=QTableWidgetItem(text);item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    if tooltip:item.setToolTip(tooltip)
    return item


class BatchEnhancerWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('Video Enhancer · 폴더 일괄 처리');self.resize(900,650)
        self.worker=None;self.rows={};self.regions={};self.invalid_regions=[];self._close_after=False
        self.selected_files=None
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('영상 폴더'))
        self.folder_label=QLabel(str(Path.cwd()));self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.folder_label.setWordWrap(True);row.addWidget(self.folder_label,1)
        self.files_button=QPushButton('파일 선택');self.files_button.clicked.connect(self.choose_files);row.addWidget(self.files_button)
        self.folder_button=QPushButton('폴더 선택');self.folder_button.clicked.connect(self.choose_folder);row.addWidget(self.folder_button)
        self.scan_button=QPushButton('다시 읽기');self.scan_button.clicked.connect(self.scan);row.addWidget(self.scan_button)

        effects=QHBoxLayout();layout.addLayout(effects)
        self.watermark=QCheckBox('워터마크 지우기 (화면 크기 유지)');self.watermark.setChecked(True);effects.addWidget(self.watermark)
        effects.addWidget(QLabel('기본: Hailuo AI + Gemini'))
        self.stabilize=QCheckBox('흔들림 보정');effects.addWidget(self.stabilize)
        self.interpolate=QCheckBox('프레임 보간 (2배 FPS)');effects.addWidget(self.interpolate)
        effects.addStretch(1)
        note=QLabel('워터마크는 주변 픽셀로 메우며 화면 크기와 자막 위치를 유지합니다. 미리보기에서 실제 로고 위치를 확인·조정하세요. '
                    '결과는 video_manager_output에 저장됩니다. 원본·설정·처리 방식이 같은 완료 파일만 건너뜁니다.')
        note.setWordWrap(True);layout.addWidget(note)

        self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['영상 파일','상태'])
        self.table.horizontalHeader().setStretchLastSection(False);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.table.setColumnWidth(1,230);layout.addWidget(self.table,1)
        self.table.cellDoubleClicked.connect(lambda *_:self.preview_regions())
        self.progress_bar=QProgressBar();layout.addWidget(self.progress_bar)
        self.progress_label=QLabel('폴더를 선택하면 영상 목록을 불러옵니다.');layout.addWidget(self.progress_label)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        self.run_button=QPushButton('미완료 파일 처리');self.run_button.clicked.connect(self.start_batch);buttons.addWidget(self.run_button)
        self.preview_button=QPushButton('선택 파일 영역 미리보기');self.preview_button.clicked.connect(self.preview_regions);buttons.addWidget(self.preview_button)
        self.cancel_button=QPushButton('현재 파일 후 중지');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel_batch);buttons.addWidget(self.cancel_button)
        self.open_output_button=QPushButton('결과 폴더 열기');self.open_output_button.clicked.connect(self.open_output);buttons.addWidget(self.open_output_button)
        for control in (self.watermark,self.stabilize,self.interpolate):control.toggled.connect(self.scan)
        self.folder_label.setText(str(Path.cwd()));self.scan()

    def file_options(self,source):
        watermark=dict(enabled=self.watermark.isChecked(),profile='both_inpaint')
        if str(source) in self.regions and self.regions[str(source)]!=[list(region) for region in DEFAULT_REGIONS]:
            watermark['regions']=self.regions[str(source)]
        return dict(interpolation=dict(enabled=self.interpolate.isChecked(),backend='cpu_flow'),
                    stabilization=dict(enabled=self.stabilize.isChecked()),watermark=watermark)

    def preview_regions(self):
        if self.worker is not None:return
        row=self.table.currentRow()
        if row<0:
            QMessageBox.information(self,'파일 선택','목록에서 확인할 영상을 선택하세요.');return
        source=next(Path(path) for path,index in self.rows.items() if index==row)
        from .watermark_preview import WatermarkPreview
        dialog=WatermarkPreview(source,self.regions.get(str(source)),self,mode='inpaint')
        if dialog.exec():
            try:save_regions(output_path(source,self.output_root(source)),dialog.regions)
            except Exception as exc:QMessageBox.warning(self,'영역 저장 실패',str(exc));return
            self.scan();self.table.selectRow(row)

    def choose_folder(self):
        current=str(self.selected_files[0].parent) if self.selected_files else self.folder_label.text()
        folder=QFileDialog.getExistingDirectory(self,'영상 폴더 선택',current)
        if folder:self.selected_files=None;self.folder_label.setText(folder);self.scan()

    def choose_files(self):
        current=(str(Path(self.folder_label.text())) if Path(self.folder_label.text()).is_dir()
                 else str(self.selected_files[0].parent) if self.selected_files else str(Path.cwd()))
        paths,_=QFileDialog.getOpenFileNames(self,'영상 파일 선택',current,
            'Video files (*.mp4 *.mov *.mkv *.avi *.m4v *.webm);;All files (*)')
        if not paths:return
        files=list(dict.fromkeys(Path(path).expanduser().resolve() for path in paths
                                 if Path(path).suffix.lower() in VIDEO_EXTENSIONS))
        if not files:
            QMessageBox.information(self,'영상 파일 없음','지원하는 영상 파일을 선택하세요.');return
        self.selected_files=files
        self.folder_label.setText(f'{len(files)}개 파일 선택됨')
        self.scan()

    def output_root(self,source):
        return Path(source).parent if self.selected_files is not None else Path(self.folder_label.text())

    def selected_sources(self):
        return list(self.selected_files) if self.selected_files is not None else discover_videos(Path(self.folder_label.text()))

    def scan(self):
        if self.worker is not None:return
        folder=Path(self.folder_label.text())
        try:files=self.selected_sources()
        except Exception as exc:
            QMessageBox.warning(self,'폴더 오류',str(exc));return
        self.table.setRowCount(0);self.rows={};self.regions={};self.invalid_regions=[]
        for source in files:
            row=self.table.rowCount();self.table.insertRow(row)
            self.table.setItem(row,0,_table_item(source.name,str(source)))
            destination=output_path(source,self.output_root(source))
            try:
                regions=load_regions(destination)
                if regions is not None:self.regions[str(source)]=regions
                done=is_completed(source,destination,self.file_options(source))
                status='완료' if done else ('재처리 필요' if destination.exists() else '대기')
            except Exception as exc:
                status=f'영역 설정 오류: {exc}';self.invalid_regions.append(str(source))
            self.table.setItem(row,1,_table_item(status,str(destination)))
            self.rows[str(source)]=row
        self.progress_bar.setRange(0,max(1,len(files)));self.progress_bar.setValue(sum(
            self.table.item(row,1).text()=='완료' for row in range(self.table.rowCount())))
        output_note=('선택 파일이 있는 폴더의 video_manager_output' if self.selected_files is not None
                     else str(folder/OUTPUT_FOLDER))
        self.progress_label.setText(f'{len(files)}개 영상 · 결과 폴더: {output_note}')

    def start_batch(self):
        if self.worker is not None:return
        self.scan()
        if self.invalid_regions:
            QMessageBox.warning(self,'영역 설정 오류','영역 미리보기에서 오류 파일의 영역을 다시 저장하세요.');return
        folder=Path(self.folder_label.text())
        try:files=self.selected_sources()
        except Exception as exc:QMessageBox.warning(self,'폴더 오류',str(exc));return
        if not files:QMessageBox.information(self,'영상 없음','선택한 폴더에 지원하는 영상 파일이 없습니다.');return
        options=self.file_options(files[0])
        if not any(options[k]['enabled'] for k in ('interpolation','stabilization','watermark')):
            QMessageBox.information(self,'효과 선택','워터마크 제거, 흔들림 보정, 프레임 보간 중 하나 이상 선택하세요.');return
        configs={str(source):self.file_options(source) for source in files}
        self.worker=BatchWorker(files,folder,configs,self.interpolate.isChecked(),
                                per_source_folder=self.selected_files is not None,parent=self)
        self.worker.item_status.connect(self.set_item_status);self.worker.progress.connect(self.set_progress)
        self.worker.finished_batch.connect(self.batch_finished)
        self.worker.finished.connect(self.thread_finished)
        self.set_busy(True);self.progress_bar.setRange(0,len(files));self.progress_bar.setValue(0)
        self.worker.start()

    def set_item_status(self,path,status):
        row=self.rows.get(path)
        if row is not None:
            item=_table_item(status)
            if status.startswith('오류:'):item.setToolTip(status)
            self.table.setItem(row,1,item)

    def set_progress(self,current,total,message):
        self.progress_bar.setValue(current);self.progress_label.setText(f'{current}/{total} · {message}')

    def cancel_batch(self):
        if self.worker:self.worker.cancel();self.progress_label.setText('현재 처리 중인 파일을 마친 뒤 중지합니다.')

    def batch_finished(self,completed,failed,cancelled):
        state='중지됨' if cancelled else ('처리 종료' if failed else '모든 파일 처리 완료')
        self.progress_label.setText(f'{state} · 완료 {completed}개 · 오류 {failed}개')

    def thread_finished(self):
        self.worker.deleteLater()
        self.worker=None
        self.set_busy(False)
        if self._close_after:self.close()

    def closeEvent(self,event):
        if self.worker is not None:
            self._close_after=True;self.cancel_batch();event.ignore()
        else:event.accept()

    def set_busy(self,busy):
        for widget in (self.folder_button,self.files_button,self.scan_button,self.run_button,self.preview_button,self.stabilize,self.interpolate,
                       self.watermark):widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def open_output(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        if self.selected_files is not None and self.selected_files:
            folder=self.selected_files[0].parent/OUTPUT_FOLDER
        else:folder=Path(self.folder_label.text())/OUTPUT_FOLDER
        folder.mkdir(parents=True,exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def main():
    app=QApplication.instance() or QApplication(sys.argv)
    window=BatchEnhancerWindow();window.show()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
