"""Desktop workflow built on the same strict job schema and process-based engine."""
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import time
from types import SimpleNamespace
import uuid

from PySide6.QtCore import Qt,QThread,Signal,QProcess,QUrl,QTimer
from PySide6.QtGui import QBrush,QColor,QDesktopServices,QFont,QFontDatabase,QPixmap
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,
    QTableWidget,QTableWidgetItem,QPushButton,QLabel,QLineEdit,QDoubleSpinBox,QFileDialog,QMessageBox,
    QProgressBar,QPlainTextEdit,QTextBrowser,QComboBox,QHeaderView,QCheckBox,QListWidget,
    QFontComboBox,QSpinBox,QColorDialog,QScrollArea,QSlider,QAbstractItemView)

from ..errors import InputError
from ..internal_motion import load_selections
from ..job_schema import load_job,normalize_job,save_job
from ..probe import probe
from ..timing_reference import load_master_timings
from .viewer import ComparisonViewer,SpeedPlot


class ProbeThread(QThread):
    result=Signal(str,object)
    def __init__(self,path,parent=None):
        super().__init__(parent);self.path=path
    def run(self):
        try:
            clip=probe(Path(self.path).resolve(),'metadata')
            self.result.emit(self.path,{'duration':clip.duration,'fps':str(clip.fps)})
        except Exception as exc:self.result.emit(self.path,{'error':str(exc)})


class PreviewCopyThread(QThread):
    copied=Signal(str)
    def __init__(self,source,temporary,parent=None):
        super().__init__(parent);self.source=source;self.temporary=temporary
        self.copy=Path(temporary.name)/source.name
    def run(self):
        try:
            source=self.source
            if not source.is_file():source=source.parent.parent/'results'/source.name
            shutil.copyfile(source,self.copy)
            self.copied.emit('')
        except Exception as exc:self.copied.emit(str(exc))


class SubtitlePreviewThread(QThread):
    rendered=Signal(str,str)
    def __init__(self,config,start,output,parent=None):
        super().__init__(parent);self.config=config;self.start_seconds=start;self.output=output
    def run(self):
        try:
            from ..narration import render_subtitle_preview
            path=render_subtitle_preview(self.config,self.start_seconds,self.output)
            self.rendered.emit(str(path),'')
        except Exception as exc:self.rendered.emit('',str(exc))


class SubtitleStillThread(QThread):
    rendered=Signal(int,str,str)
    def __init__(self,request,config,start,output,parent=None):
        super().__init__(parent);self.request=request;self.config=config;self.start_seconds=start;self.output=output
    def run(self):
        try:
            from ..narration import render_subtitle_still
            path=render_subtitle_still(self.config,self.start_seconds,self.output)
            self.rendered.emit(self.request,str(path),'')
        except Exception as exc:self.rendered.emit(self.request,'',str(exc))


def item(value='',checked=None,editable=True):
    widget=QTableWidgetItem(str(value))
    if checked is not None:
        widget.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable|Qt.ItemIsUserCheckable)
        widget.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    elif not editable:widget.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
    return widget


class MainWindow(QMainWindow):
    workerFinished=Signal(str)

    def __init__(self):
        super().__init__();self.setWindowTitle('Video Manager · timing and motion review');self.resize(1200,850)
        self._loading=False;self.revision=0;self.result_revision=None;self.result_dir=None
        self._master_json_path=None;self._master_json_data=None;self._pending_save_path=None
        self.narration_fields={}
        self._subtitle_application_fonts=[]
        self._subtitle_preview_thread=None;self._subtitle_preview_temp=None;self._subtitle_preview_path=None
        self._subtitle_still_temp=tempfile.TemporaryDirectory(prefix='video-manager-subtitle-stills-')
        self._subtitle_still_request=0;self._subtitle_still_workers=[];self._subtitle_still_path=None
        self.report_paths=[];self.preview_paths={};self.preview_reasons={};self.probers=[];self._temporary=None
        self._cancel_requested=False;self._worker_ready=False;self._active_kind=None;self._active_output=None
        self._live_preview_copy=None;self._live_preview_paths=set()
        self._live_preview_request=0;self._live_preview_workers=[]
        self.watermark_regions=None
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        for label,callback in [('Add clips',self.choose_clips),('Load JSON',self.choose_load),
                               ('Save JSON',self.choose_save),('Inspect motion',self.start_inspection),
                               ('Load motion report',self.choose_motion_report),('Clear motion',self.clear_motion),('Load results',self.choose_results)]:
            button=QPushButton(label);button.clicked.connect(lambda _=False,fn=callback:self.guarded(fn));toolbar.addWidget(button)
        self.run_button=QPushButton('Run job');self.run_button.clicked.connect(lambda:self.guarded(self.start_job));toolbar.addWidget(self.run_button)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel_job);toolbar.addWidget(self.cancel_button)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        clip_page=QWidget();cl=QVBoxLayout(clip_page);self.tabs.addTab(clip_page,'Clips & timing')
        self.json_label=QLabel('Loaded JSON: none');self.json_label.setWordWrap(True)
        self.json_label.setTextFormat(Qt.PlainText);self.json_label.setTextInteractionFlags(Qt.TextSelectableByMouse);cl.addWidget(self.json_label)
        self.timing_summary=QLabel('Current targets: 0 clips · total 0s');cl.addWidget(self.timing_summary)
        self.independent_check=QCheckBox('Process clips independently (do not join them)')
        self.independent_check.setToolTip('Shorten each input to its Target and save separate video files. A PNG of each result’s last frame is saved beside it. Boundary processing, selected motion regions, and narration are unavailable in this mode.')
        cl.addWidget(self.independent_check)
        self.clip_table=QTableWidget(0,9);self.clip_table.setHorizontalHeaderLabels(['Enabled','ID','Path','Source seconds','Target','Protect','Max speed','Ramp','JSON target'])
        self.clip_table.horizontalHeaderItem(0).setToolTip(
            'Clip correction switch. Off keeps the clip in the timeline but disables timing correction, stabilization and interpolation at both adjacent boundaries. Fixed mark removal still applies. '
            'A different Target duration requires this switch on.')
        self.clip_table.horizontalHeaderItem(8).setToolTip('Target seconds imported from JSON. Compare with the editable Target column.')
        self.clip_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.clip_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.clip_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch);cl.addWidget(self.clip_table)
        row=QHBoxLayout();cl.addLayout(row)
        for label,fn in [('Remove selected',self.remove_clip),('Move up',lambda:self.move_clip(-1)),('Move down',lambda:self.move_clip(1))]:
            button=QPushButton(label);button.clicked.connect(fn);row.addWidget(button)
        row.addWidget(QLabel('Output directory'))
        self.output_edit=QLineEdit(str(Path.cwd()/'outputs'/f'ui-job-{uuid.uuid4().hex[:8]}'));row.addWidget(self.output_edit,1)
        row.addWidget(QLabel('Audio'))
        self.audio_mode_combo=QComboBox()
        self.audio_mode_combo.addItem('Keep original audio','preserve')
        self.audio_mode_combo.addItem('Mute source audio','mute')
        self.audio_mode_combo.setToolTip('Keeps speech, music, and effects. Audio follows the clip timing; playback speed changes pitch.')
        row.addWidget(self.audio_mode_combo)
        self.fps_spin=QDoubleSpinBox();self.fps_spin.setRange(0,120);self.fps_spin.setDecimals(9);self.fps_spin.setSpecialValueText('First source FPS');row.addWidget(self.fps_spin)
        self.boundary_table=QTableWidget(0,7);self.boundary_table.setHorizontalHeaderLabels(['From','To','Enabled','Window','Strength','Local speed','Duplicate policy'])
        self.boundary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.tabs.addTab(self.boundary_table,'Boundaries')
        motion_page=QWidget();ml=QVBoxLayout(motion_page);self.motion_page=motion_page;self.tabs.addTab(motion_page,'Internal motion')
        self.motion_review_instructions=QLabel(
            '검토 순서: Source range·Kinds·Evidence·Confidence를 확인하고, 행을 두 번 눌러 원본/제안 비교를 보세요. '
            '제안이 실제 잘못된 정지·반복 구간을 고칠 때만 Select를 체크하세요. 의도된 카메라 이동·정지이거나 확신이 없으면 선택하지 마세요. '
            'Exclude가 Select보다 우선합니다. 선택은 자동 적용되지 않습니다. 검토 후 Save JSON, 이어서 Run job을 실행하세요.')
        self.motion_review_instructions.setWordWrap(True);ml.addWidget(self.motion_review_instructions)
        self.motion_summary=QLabel('No motion analysis loaded');self.motion_summary.setWordWrap(True);ml.addWidget(self.motion_summary)
        self.motion_table=QTableWidget(0,8);self.motion_table.setHorizontalHeaderLabels(['Select','Exclude','Region ID','Source range','Kinds','Evidence','Confidence','Review / skipped reason'])
        self.motion_table.horizontalHeader().setSectionResizeMode(5,QHeaderView.Stretch);ml.addWidget(self.motion_table)
        effects_page=QWidget();el=QVBoxLayout(effects_page);self.tabs.addTab(effects_page,'Video enhancements')
        explanation=QLabel('Optional processing for Run job. Timing, interpolation and stabilization preserve first/last frames and the protected opening. '
            'Watermark removal defaults to the Video Enhancer crop method; preview and adjust the logo regions before running. Inpaint modes remain available.')
        explanation.setWordWrap(True);el.addWidget(explanation)
        help_row=QHBoxLayout();help_row.addStretch()
        self.enhancement_help_button=QPushButton('기능 설명 (HTML)')
        self.enhancement_help_button.clicked.connect(lambda:self.guarded(self.open_enhancement_help))
        help_row.addWidget(self.enhancement_help_button);el.addLayout(help_row)
        self.interpolate_check=QCheckBox('Frame interpolation');el.addWidget(self.interpolate_check)
        self.interpolate_check.setToolTip('Generate intermediate frames at requested source times. CPU processing may be slow.')
        self.stabilize_check=QCheckBox('Camera stabilization');el.addWidget(self.stabilize_check)
        self.stabilize_check.setToolTip('Reduce small camera shake. This moves and crops image pixels; intentional zoom is left unchanged. High-quality CPU reconstruction can be slow at full resolution.')
        self.stabilize_strength=QDoubleSpinBox();self.stabilize_strength.setRange(0,1);self.stabilize_strength.setSingleStep(.1);self.stabilize_strength.setValue(.7)
        self.stabilize_smoothing=QDoubleSpinBox();self.stabilize_smoothing.setRange(.05,2);self.stabilize_smoothing.setSingleStep(.05);self.stabilize_smoothing.setValue(.4)
        self.crop_percent=QDoubleSpinBox();self.crop_percent.setRange(0,15);self.crop_percent.setSuffix(' %');self.crop_percent.setValue(5)
        for control in (self.stabilize_strength,self.stabilize_smoothing,self.crop_percent):control.setDecimals(6)
        for label,control in [('Stabilization strength',self.stabilize_strength),('Smoothing seconds',self.stabilize_smoothing),('Maximum crop (total width / height)',self.crop_percent)]:
            control_row=QHBoxLayout();control_row.addWidget(QLabel(label));control_row.addWidget(control);el.addLayout(control_row)
        self.crop_percent.setToolTip('Maximum total width/height removed by crop zoom. Translation and rotation can make edge losses unequal. Zero allows no crop.')
        watermark_row=QHBoxLayout();el.addLayout(watermark_row)
        self.watermark_check=QCheckBox('Remove watermarks');self.watermark_check.setChecked(True);watermark_row.addWidget(self.watermark_check)
        self.watermark_profile=QComboBox()
        self.watermark_profile.addItem('Avoid Gemini + Hailuo logos by cropping (Enhancer)', 'both')
        self.watermark_profile.addItem('Inpaint fixed Gemini logo', 'gemini')
        self.watermark_profile.addItem('Inpaint fixed Hailuo logo', 'hailuo')
        self.watermark_profile.addItem('Inpaint custom fixed mask', 'custom')
        watermark_row.addWidget(self.watermark_profile,1)
        self.watermark_preview_button=QPushButton('Preview / set crop regions')
        self.watermark_preview_button.clicked.connect(lambda:self.guarded(self.preview_watermark_regions))
        watermark_row.addWidget(self.watermark_preview_button)
        self.watermark_check.setToolTip('Removes logos by cropping them out (default) or inpainting a fixed logo mask.')
        mask_widget=QWidget();self.watermark_mask_widget=mask_widget
        mask_row=QHBoxLayout(mask_widget);el.addWidget(mask_widget)
        self.mark_center_x=QDoubleSpinBox();self.mark_center_y=QDoubleSpinBox()
        self.mark_width=QDoubleSpinBox();self.mark_height=QDoubleSpinBox()
        for label,control,value in [('Center X',self.mark_center_x,90.625),('Center Y',self.mark_center_y,83.333333),
                                    ('Mask width',self.mark_width,5.5),('Mask height',self.mark_height,10.0)]:
            control.setRange(0 if control in (self.mark_center_x,self.mark_center_y) else .001,
                             100 if control in (self.mark_center_x,self.mark_center_y) else 25)
            control.setDecimals(6);control.setValue(value);control.setSuffix(' %')
            mask_row.addWidget(QLabel(label));mask_row.addWidget(control)
        self.mark_width.setToolTip('Width of the inpaint mask as a percentage of source image width.')
        self.mark_height.setToolTip('Height of the inpaint mask as a percentage of source image height.')
        el.addStretch()
        narration_page=QWidget();nl=QVBoxLayout(narration_page)
        narration_note=QLabel('세 파일을 등록한 뒤 검사 결과를 확인하세요. Run job에서 TTS 전체 길이를 영상에 맞추고 자막을 화면에 넣습니다. 원본 음향 유지 시 35%로 낮춰 TTS와 섞습니다. 문장별 발화 동기화는 결과를 들으며 확인해야 합니다.')
        narration_note.setWordWrap(True);nl.addWidget(narration_note)
        narration_guide=QTextBrowser();self.narration_guide=narration_guide;narration_guide.setMaximumHeight(235)
        narration_guide.setHtml('''
          <b>예시 프로젝트에서 고를 파일</b>
          <ol>
            <li><b>TTS audio</b>에는 실제 음성 파일 <code>스페인TTS.mp3</code>를 선택합니다.</li>
            <li><b>Final video subtitles</b>에는 120초 완성 영상 기준인 <code>Spanish_Armada_Subtitles_120s_Resolve.srt</code>를 선택합니다. 최종 영상에서 자막을 어느 시각에 보여줄지 기준입니다.</li>
            <li><b>Subtitle to 30-shot mapping</b>에는 <code>TTS_Subtitle_30Shot_Mapping.csv</code>를 선택합니다. 영상 컷마다 어떤 자막이 걸리는지 연결합니다. 예: <code>01-01</code> 샷은 0–4초이고 자막 1, 2와 겹칩니다.</li>
          </ol>
          <p><b>필요한 파일은 위 세 개뿐입니다.</b> 별도의 추정 타이밍 SRT나 상세 타이밍 CSV는 업로드하지 않아도 됩니다.</p>
        ''')
        narration_guide.setReadOnly(True);nl.addWidget(narration_guide)
        narration_rows=[
            ('audio_path','TTS audio · 음성 원본','MP3/WAV audio (*.mp3 *.wav)'),
            ('subtitle_srt','Final video subtitles · 최종 영상 SRT','SubRip subtitles (*.srt)'),
            ('shot_mapping_csv','Subtitle to 30-shot mapping · 컷 매핑 CSV','CSV files (*.csv)'),
        ]
        for key,title,filters in narration_rows:
            file_row=QHBoxLayout();file_row.addWidget(QLabel(title))
            field=QLineEdit();field.setReadOnly(True);field.setPlaceholderText('No file selected')
            field.setToolTip('Select a file. The full path is stored in the job JSON.')
            file_row.addWidget(field,1);self.narration_fields[key]=field
            browse=QPushButton('Select…');browse.clicked.connect(lambda _=False,k=key,f=filters:self.choose_narration_file(k,f))
            clear=QPushButton('Clear');clear.clicked.connect(lambda _=False,k=key:self.clear_narration_file(k))
            file_row.addWidget(browse);file_row.addWidget(clear);nl.addLayout(file_row)
        self.narration_summary=QLabel('0 files selected');self.narration_summary.setWordWrap(True);nl.addWidget(self.narration_summary)
        self._update_narration_summary()
        narration_check=QPushButton('TTS · SRT · CSV 검사')
        narration_check.clicked.connect(lambda:self.guarded(self.check_narration_files))
        nl.addWidget(narration_check)
        style_row=QHBoxLayout();nl.addLayout(style_row)
        self.subtitle_font=QFontComboBox();self.subtitle_font.setCurrentFont(QFont('Malgun Gothic'))
        style_row.addWidget(QLabel('자막 폰트'));style_row.addWidget(self.subtitle_font,1)
        self.subtitle_font_file=QLineEdit();self.subtitle_font_file.setReadOnly(True)
        self.subtitle_font_file.setPlaceholderText('선택 사항 · TTF / OTF / TTC')
        style_row.addWidget(self.subtitle_font_file,1)
        self.subtitle_font_file_button=QPushButton('폰트 파일 추가')
        self.subtitle_font_file_button.clicked.connect(lambda:self.guarded(self.choose_subtitle_font_file))
        style_row.addWidget(self.subtitle_font_file_button)
        self.subtitle_size=QSpinBox();self.subtitle_size.setRange(8,96);self.subtitle_size.setValue(34)
        style_row.addWidget(QLabel('크기'));style_row.addWidget(self.subtitle_size)
        style_row.addWidget(QLabel('세로 위치'))
        self.subtitle_position=QSlider(Qt.Horizontal);self.subtitle_position.setRange(5,95)
        self.subtitle_position.setValue(88);self.subtitle_position.setToolTip('슬라이더를 움직여 자막 높이를 세밀하게 조절합니다.')
        style_row.addWidget(self.subtitle_position,1)
        self.subtitle_position_label=QLabel('88% · 하단');style_row.addWidget(self.subtitle_position_label)
        self.subtitle_alignment=QComboBox()
        for label,value in [('왼쪽','left'),('가운데','center'),('오른쪽','right')]:self.subtitle_alignment.addItem(label,value)
        style_row.addWidget(QLabel('가로 정렬'));style_row.addWidget(self.subtitle_alignment)
        self.subtitle_margin=QSpinBox();self.subtitle_margin.setRange(0,400);self.subtitle_margin.setValue(48)
        style_row.addWidget(QLabel('가장자리 여백'));style_row.addWidget(self.subtitle_margin)
        style_row2=QHBoxLayout();nl.addLayout(style_row2)
        self.subtitle_color_button=QPushButton('글자색: 흰색');style_row2.addWidget(self.subtitle_color_button)
        self.subtitle_color='#FFFFFF';self.subtitle_color_button.clicked.connect(lambda:self.guarded(self.choose_subtitle_color))
        self.subtitle_bold=QCheckBox('굵게');self.subtitle_bold.setChecked(True);style_row2.addWidget(self.subtitle_bold)
        self.subtitle_outline=QCheckBox('검은 외곽선');self.subtitle_outline.setChecked(True);style_row2.addWidget(self.subtitle_outline)
        self.subtitle_outline_size=QSpinBox();self.subtitle_outline_size.setRange(0,8);self.subtitle_outline_size.setValue(2)
        style_row2.addWidget(QLabel('외곽선'));style_row2.addWidget(self.subtitle_outline_size)
        self.subtitle_background=QCheckBox('배경');style_row2.addWidget(self.subtitle_background)
        self.subtitle_background_color_button=QPushButton('배경색: 검정');style_row2.addWidget(self.subtitle_background_color_button)
        self.subtitle_background_color='#000000'
        self.subtitle_background_color_button.clicked.connect(lambda:self.guarded(self.choose_subtitle_background_color))
        self.subtitle_background_opacity=QSpinBox();self.subtitle_background_opacity.setRange(0,100)
        self.subtitle_background_opacity.setValue(55);self.subtitle_background_opacity.setSuffix(' %')
        style_row2.addWidget(QLabel('배경 불투명도'));style_row2.addWidget(self.subtitle_background_opacity)
        self.subtitle_preset=QComboBox()
        self.subtitle_preset.addItem('추천 · 흰 글자 + 검은 외곽선','general')
        self.subtitle_preset.addItem('부드러운 검정 상자 · 55%','black_soft')
        self.subtitle_preset.addItem('진한 검정 상자 · 78%','black_strong')
        self.subtitle_preset.addItem('밝은 상자 · 검정 글자','white_box')
        self.subtitle_preset.addItem('다큐형 · 좌측 하단 차콜 상자','documentary')
        self.subtitle_preset.addItem('강조형 · 노랑 글자','yellow')
        style_row2.addWidget(self.subtitle_preset,1)
        self.subtitle_preset.setToolTip('목록에서 고르면 배경과 글자 조합이 즉시 적용됩니다.')
        preview_row=QHBoxLayout();nl.addLayout(preview_row)
        preview_row.addWidget(QLabel('샘플 시작 시각 (초)'))
        self.subtitle_preview_start=QDoubleSpinBox();self.subtitle_preview_start.setRange(0,86400)
        self.subtitle_preview_start.setDecimals(2);preview_row.addWidget(self.subtitle_preview_start)
        self.subtitle_preview_button=QPushButton('자막 샘플 만들기 (최대 5초)')
        self.subtitle_preview_button.clicked.connect(lambda:self.guarded(self.start_subtitle_preview))
        preview_row.addWidget(self.subtitle_preview_button)
        preview_row.addStretch()
        self.subtitle_preview_status=QLabel('샘플은 원본 클립과 TTS 위에 현재 자막 스타일을 적용합니다.')
        self.subtitle_preview_status.setWordWrap(True);nl.addWidget(self.subtitle_preview_status)
        self.subtitle_still_status=QLabel('자막 파일을 선택하면 현재 시각 프레임에 자막을 바로 표시합니다.')
        self.subtitle_still_status.setWordWrap(True);nl.addWidget(self.subtitle_still_status)
        self.subtitle_still_image=QLabel('실시간 자막 미리보기')
        self.subtitle_still_image.setAlignment(Qt.AlignCenter)
        self.subtitle_still_image.setMinimumSize(900,506)
        self.subtitle_still_image.setStyleSheet('background:#20242b;color:#e4e7eb;')
        nl.addWidget(self.subtitle_still_image)
        self.subtitle_style_tip=QLabel(
            '추천: 흰색 굵은 글자 + 검은 외곽선이 대부분의 장면에서 읽기 쉽습니다. '
            '밝거나 디테일이 많은 화면에서는 반투명 검정 배경(불투명도 55~70%)을 켜고, '
            '하단 안전 여백은 40~60 정도로 두세요. 적용 후 샘플에서 긴 문장과 밝은 장면도 확인하세요.')
        self.subtitle_style_tip.setWordWrap(True);nl.addWidget(self.subtitle_style_tip)
        self.subtitle_preview_viewer=ComparisonViewer();nl.addWidget(self.subtitle_preview_viewer,1)
        self.subtitle_preview_open=QPushButton('소리와 함께 샘플 열기');self.subtitle_preview_open.setEnabled(False)
        self.subtitle_preview_open.clicked.connect(lambda:self.guarded(self.open_subtitle_preview))
        nl.addWidget(self.subtitle_preview_open)
        for control,signal in ((self.subtitle_font,self.subtitle_font.currentFontChanged),
                               (self.subtitle_size,self.subtitle_size.valueChanged),
                               (self.subtitle_position,self.subtitle_position.valueChanged),
                               (self.subtitle_alignment,self.subtitle_alignment.currentIndexChanged),
                               (self.subtitle_margin,self.subtitle_margin.valueChanged),
                               (self.subtitle_background,self.subtitle_background.toggled),
                               (self.subtitle_background_opacity,self.subtitle_background_opacity.valueChanged),
                               (self.subtitle_outline,self.subtitle_outline.toggled),
                               (self.subtitle_outline_size,self.subtitle_outline_size.valueChanged),
                               (self.subtitle_bold,self.subtitle_bold.toggled)):
            signal.connect(self.mark_dirty)
        self.subtitle_position.valueChanged.connect(self._subtitle_position_changed)
        self.subtitle_preset.currentIndexChanged.connect(lambda *_:self.apply_subtitle_preset())
        nl.addStretch()
        narration_scroll=QScrollArea();narration_scroll.setWidgetResizable(True);narration_scroll.setWidget(narration_page)
        self.tabs.addTab(narration_scroll,'Narration / TTS')
        self.narration_page=narration_scroll
        review_page=QWidget();self.review_page=review_page;rl=QVBoxLayout(review_page);self.tabs.addTab(review_page,'Review & results')
        self.comparison_combo=QComboBox();rl.addWidget(self.comparison_combo)
        self.enhancement_summary=QPlainTextEdit();self.enhancement_summary.setReadOnly(True)
        self.enhancement_summary.setMaximumHeight(80);self.enhancement_summary.hide();rl.addWidget(self.enhancement_summary)
        self.viewer=ComparisonViewer();rl.addWidget(self.viewer,1)
        self.timeline_table=QTableWidget(0,5);self.timeline_table.setHorizontalHeaderLabels(['Clip','Start','End','Measured seconds','Error'])
        self.timeline_table.setMaximumHeight(130);rl.addWidget(self.timeline_table)
        self.curve=SpeedPlot();rl.addWidget(self.curve)
        self.final_video_button=QPushButton('Play final video in system player')
        self.final_video_button.setToolTip('Open corrected.mp4 in the default video player; audio plays when the result contains an audio stream.')
        self.final_video_button.setEnabled(False)
        self.final_video_button.clicked.connect(lambda:self.guarded(self.play_final_video))
        rl.addWidget(self.final_video_button)
        open_button=QPushButton('Open result folder');open_button.clicked.connect(self.open_results);rl.addWidget(open_button)
        self.live_page=QWidget();live_layout=QVBoxLayout(self.live_page)
        self.live_status=QLabel('Finished boundary comparison videos appear here during Run job.')
        self.live_status.setWordWrap(True);live_layout.addWidget(self.live_status)
        self.live_final_button=QPushButton('Play final video with audio')
        self.live_final_button.setEnabled(False)
        self.live_final_button.clicked.connect(lambda:self.guarded(self.play_final_video))
        live_layout.addWidget(self.live_final_button)
        self.live_list=QListWidget();self.live_list.setMaximumHeight(135);live_layout.addWidget(self.live_list)
        self.live_viewer=ComparisonViewer();live_layout.addWidget(self.live_viewer,1)
        self.tabs.addTab(self.live_page,'Final / Live previews')
        self.json_preview=QPlainTextEdit();self.json_preview.setReadOnly(True)
        self.json_preview.setPlaceholderText('Load JSON to inspect the original values here.')
        self.tabs.addTab(self.json_preview,'Loaded JSON')
        self.state_label=QLabel('Ready · original audio will be retained');layout.addWidget(self.state_label)
        self.progress=QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0);layout.addWidget(self.progress)
        self.time_label=QLabel('Elapsed: — · Stage remaining: —');layout.addWidget(self.time_label)
        self.work_timer=QTimer(self);self.work_timer.setInterval(500);self.work_timer.timeout.connect(self._update_work_time)
        self._started_at=None;self._stage='Preparing';self._stage_started=0;self._stage_done=0;self._stage_total=0
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(100);layout.addWidget(self.log)
        self.process=QProcess(self);self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.clip_table.cellChanged.connect(self._clip_changed)
        self.boundary_table.cellChanged.connect(lambda *_:self.mark_dirty())
        self.motion_table.cellChanged.connect(lambda *_:self.mark_dirty())
        self.motion_table.cellDoubleClicked.connect(lambda row,_:self.preview_region(row))
        self.output_edit.textChanged.connect(self.mark_dirty);self.fps_spin.valueChanged.connect(self.mark_dirty)
        self.audio_mode_combo.currentIndexChanged.connect(self.mark_dirty)
        self.independent_check.toggled.connect(self.mark_dirty)
        self.independent_check.toggled.connect(self._set_independent_mode)
        self.interpolate_check.toggled.connect(self.mark_dirty);self.stabilize_check.toggled.connect(self.mark_dirty)
        self.watermark_check.toggled.connect(self.mark_dirty)
        self.watermark_profile.currentIndexChanged.connect(self.mark_dirty)
        self.watermark_profile.currentIndexChanged.connect(self._update_watermark_profile)
        for control in (self.stabilize_strength,self.stabilize_smoothing,self.crop_percent):control.valueChanged.connect(self.mark_dirty)
        for control in (self.mark_center_x,self.mark_center_y,self.mark_width,self.mark_height):control.valueChanged.connect(self.mark_dirty)
        self.comparison_combo.currentIndexChanged.connect(self._comparison_changed)
        self.subtitle_preview_start.valueChanged.connect(self._schedule_subtitle_still)
        self.live_list.currentItemChanged.connect(self._live_preview_selected)
        self.timeline_table.currentCellChanged.connect(self._curve_changed)
        self._update_watermark_profile()
        self._result_report=None
        self._subtitle_still_timer=QTimer(self);self._subtitle_still_timer.setSingleShot(True)
        self._subtitle_still_timer.setInterval(250);self._subtitle_still_timer.timeout.connect(self._render_subtitle_still)

    def guarded(self,callback):
        try:return callback()
        except Exception as exc:
            self.state_label.setText(f'Error: {exc}');QMessageBox.warning(self,'Video Manager',str(exc))

    def mark_dirty(self,*_):
        if self._loading:return
        self._schedule_subtitle_still()
        if self._subtitle_preview_path and self._subtitle_preview_path.is_file():
            self.subtitle_preview_status.setText('설정이 바뀌었습니다. 자막 샘플을 다시 만드세요.')
        self.update_timing_summary()
        self.revision+=1
        if self.result_dir:self.state_label.setText('Settings changed · previous result is stale; rerun to refresh')
        elif self.process.state()==QProcess.NotRunning:self.state_label.setText('Settings changed · ready to validate and run')

    def _set_independent_mode(self,enabled):
        self.tabs.setTabEnabled(self.tabs.indexOf(self.boundary_table),not enabled)

    def _update_watermark_profile(self,*_):
        profile=self.watermark_profile.currentData()
        cropping=profile=='both'
        self.watermark_mask_widget.setVisible(not cropping)
        self.watermark_preview_button.setVisible(cropping)
        if self._loading:return
        if profile=='gemini':defaults=(90.625,83.333333,5.5,10.0)
        elif profile=='hailuo':defaults=(89.0,93.2,20.0,6.5)
        else:return
        for control,value in zip((self.mark_center_x,self.mark_center_y,self.mark_width,self.mark_height),defaults):
            control.setValue(value)

    def preview_watermark_regions(self):
        row=self.clip_table.currentRow()
        if row<0:
            QMessageBox.information(self,'Select a clip','Select a clip before previewing watermark regions.')
            return
        source=Path(self.clip_table.item(row,2).text())
        from .watermark_preview import WatermarkPreview
        dialog=WatermarkPreview(source,self.watermark_regions,self)
        if dialog.exec():
            self.watermark_regions=[list(region) for region in dialog.regions]
            self.mark_dirty()

    def _clip_changed(self,row,column):
        if self._loading:return
        if column==4:self._refresh_ten_second_rows(row)
        self.mark_dirty()
        if column in [0,1,2]:self.sync_boundaries()
        if column==2 and self.clip_table.item(row,column):
            self.clip_table.item(row,8).setText('')
            self.request_probe(self.clip_table.item(row,column).text())

    def _refresh_ten_second_rows(self,only_row=None,*,disable=True):
        """Flag a 10-second target for review without overwriting edited timings."""
        previous=self._loading;self._loading=True
        try:
            rows=range(self.clip_table.rowCount()) if only_row is None else (only_row,)
            for row in rows:
                target_item=self.clip_table.item(row,4)
                try:needs_review=math.isclose(float(target_item.text()),10,rel_tol=0,abs_tol=1e-6)
                except (AttributeError,ValueError):needs_review=False
                enabled_item=self.clip_table.item(row,0)
                auto_disabled=bool(enabled_item.data(Qt.UserRole+1))
                if needs_review and disable and not auto_disabled:
                    if enabled_item.checkState()==Qt.Checked:
                        enabled_item.setData(Qt.UserRole+1,True)
                        enabled_item.setCheckState(Qt.Unchecked)
                elif not needs_review and auto_disabled:
                    enabled_item.setData(Qt.UserRole+1,False)
                    enabled_item.setCheckState(Qt.Checked)
                background=QBrush(QColor('#ffe1e1')) if needs_review else QBrush()
                foreground=QBrush(QColor('#a00000')) if needs_review else QBrush()
                tip=('Target remains 10 seconds. Check the Master timing. A clip disabled by this warning is re-enabled when its target is corrected.'
                     if needs_review else '')
                for column in range(self.clip_table.columnCount()):
                    cell=self.clip_table.item(row,column)
                    if cell is None:continue
                    cell.setBackground(background);cell.setForeground(foreground);cell.setToolTip(tip)
                header=self.clip_table.verticalHeaderItem(row)
                if header is None:
                    header=QTableWidgetItem(str(row+1));self.clip_table.setVerticalHeaderItem(row,header)
                header.setText(str(row+1));header.setBackground(background);header.setForeground(foreground)
        finally:self._loading=previous

    def update_timing_summary(self):
        total=0;invalid=0;changed=0;ten_second_targets=0
        for row in range(self.clip_table.rowCount()):
            try:
                target=float(self.clip_table.item(row,4).text())
                if not math.isfinite(target) or target<=0:raise ValueError
                total+=target
                ten_second_targets+=math.isclose(target,10,rel_tol=0,abs_tol=1e-6)
            except ValueError:
                invalid+=1;target=None
            original=self.clip_table.item(row,8).text()
            if original and (target is None or target!=float(original)):changed+=1
        text=f'Current targets: {self.clip_table.rowCount()} clips · total {total:g}s'
        if invalid:text+=f' · {invalid} missing/invalid targets'
        if changed:text+=f' · {changed} targets changed from JSON'
        if ten_second_targets:text+=f' · {ten_second_targets} 10s targets need review'
        self.timing_summary.setText(text)

    def show_loaded_json(self,path,data,targets,kind):
        self._loading=True
        try:
            for row,target in enumerate(targets):self.clip_table.item(row,8).setText(str(target))
        finally:self._loading=False
        description=f'Loaded JSON: {Path(path).resolve()}\n{kind} · imported {len(targets)} clips · target total {sum(targets):g}s'
        if kind=='Master':
            description+=f" · full plan: {len(data['records'])} clips / {sum(r['edit_duration_s'] for r in data['records']):g}s"
        self.json_label.setText(description)
        self.json_preview.setPlainText(json.dumps(data,indent=2,ensure_ascii=False))
        self.update_timing_summary()
        self.tabs.setCurrentIndex(0)

    def add_clip(self,path):
        master_target=None
        if self._master_json_path is not None:
            paths=[self.clip_table.item(row,2).text() for row in range(self.clip_table.rowCount())]
            master_target=load_master_timings(self._master_json_path,[*paths,path])[-1]
        existing={self.clip_table.item(r,1).text() for r in range(self.clip_table.rowCount())}
        index=1
        while f'clip_{index:02d}' in existing:index+=1
        self._loading=True;row=self.clip_table.rowCount();self.clip_table.insertRow(row)
        target=f'{master_target:g}' if master_target is not None else ''
        values=[item(checked=True),item(f'clip_{index:02d}'),item(str(Path(path).resolve())),item('Loading…',editable=False),item(target),item('1'),item('12'),item('0.5'),item(target,editable=False)]
        for col,value in enumerate(values):self.clip_table.setItem(row,col,value)
        self._loading=False;self._refresh_ten_second_rows(row);self.sync_boundaries();self.mark_dirty()
        if master_target is not None:
            targets=[float(self.clip_table.item(row,8).text()) for row in range(self.clip_table.rowCount())]
            self.show_loaded_json(self._master_json_path,self._master_json_data,targets,'Master')
        self.request_probe(str(Path(path).resolve()))

    def request_probe(self,path):
        worker=ProbeThread(path,self);self.probers.append(worker);worker.result.connect(self._probed)
        worker.finished.connect(lambda:self._probe_finished(worker));worker.start()

    def _probe_finished(self,worker):
        if worker in self.probers:self.probers.remove(worker)
        worker.deleteLater()

    def _probed(self,path,data):
        self._loading=True
        new_targets=[]
        for row in range(self.clip_table.rowCount()):
            if self.clip_table.item(row,2).text()==path:
                self.clip_table.item(row,3).setText('Error' if 'error' in data else f"{data['duration']:.6f}")
                if not self.clip_table.item(row,4).text() and 'duration' in data:
                    self.clip_table.item(row,4).setText(f"{data['duration']:.6f}")
                    new_targets.append(row)
        self._loading=False
        for row in new_targets:self._refresh_ten_second_rows(row)
        self.update_timing_summary()
        if 'error' in data:self.state_label.setText(data['error'])

    def remove_clip(self):
        rows=sorted({index.row() for index in self.clip_table.selectionModel().selectedRows()},reverse=True)
        if not rows and self.clip_table.currentRow()>=0:
            rows=[self.clip_table.currentRow()]
        if not rows:return
        for row in rows:self.clip_table.removeRow(row)
        self._refresh_ten_second_rows(disable=False)
        self.sync_boundaries();self.update_timing_summary();self.mark_dirty()

    def move_clip(self,delta):
        row=self.clip_table.currentRow();other=row+delta
        if not 0<=other<self.clip_table.rowCount():return
        self._loading=True
        for column in range(self.clip_table.columnCount()):
            first=self.clip_table.takeItem(row,column);second=self.clip_table.takeItem(other,column)
            self.clip_table.setItem(row,column,second);self.clip_table.setItem(other,column,first)
        self.clip_table.setCurrentCell(other,1);self._loading=False;self._refresh_ten_second_rows(disable=False);self.sync_boundaries();self.mark_dirty()

    def boundary_values(self):
        result=[]
        for row in range(self.boundary_table.rowCount()):
            t=self.boundary_table
            result.append({'from':t.item(row,0).text(),'to':t.item(row,1).text(),
                'enabled':t.item(row,2).checkState()==Qt.Checked,'window_seconds':float(t.item(row,3).text()),
                'strength':float(t.item(row,4).text()),'local_speed':t.item(row,5).checkState()==Qt.Checked,
                'duplicate_policy':t.item(row,6).text(),'mode':'manual'})
        return result

    def sync_boundaries(self,values=None):
        try:old={(b['from'],b['to']):b for b in (values if values is not None else self.boundary_values())}
        except ValueError:old={}
        loading=self._loading;self._loading=True
        ids=[self.clip_table.item(row,1).text() for row in range(self.clip_table.rowCount())]
        self.boundary_table.setRowCount(max(0,len(ids)-1))
        for row,(left,right) in enumerate(zip(ids,ids[1:])):
            data=old.get((left,right),dict(enabled=True,window_seconds=.5,strength=.3,local_speed=False,duplicate_policy='review'))
            cells=[item(left,editable=False),item(right,editable=False),item(checked=data['enabled']),item(data['window_seconds']),item(data['strength']),item(checked=data['local_speed']),item(data['duplicate_policy'])]
            for col,value in enumerate(cells):self.boundary_table.setItem(row,col,value)
        self._loading=loading

    def build_config(self):
        clips=[]
        try:
            for row in range(self.clip_table.rowCount()):
                t=self.clip_table
                clips.append(dict(id=t.item(row,1).text(),path=t.item(row,2).text(),target_seconds=float(t.item(row,4).text()),
                    protect_seconds=float(t.item(row,5).text()),max_speed=float(t.item(row,6).text()),ramp_seconds=float(t.item(row,7).text()),
                    correction_enabled=t.item(row,0).checkState()==Qt.Checked))
            boundaries=self.boundary_values()
        except ValueError as exc:raise InputError('Enter valid numbers for timing and boundary controls') from exc
        selected=[];excluded=[]
        for row in range(self.motion_table.rowCount()):
            identifier=self.motion_table.item(row,2).text()
            if self.motion_table.item(row,0).checkState()==Qt.Checked:selected.append(identifier)
            if self.motion_table.item(row,1).checkState()==Qt.Checked:excluded.append(identifier)
        watermark_options=dict(enabled=self.watermark_check.isChecked(),profile=self.watermark_profile.currentData(),
            center_x_fraction=self.mark_center_x.value()/100,
            center_y_fraction=self.mark_center_y.value()/100,
            width_fraction=self.mark_width.value()/100,
            height_fraction=self.mark_height.value()/100)
        if watermark_options['profile']=='both' and self.watermark_regions is not None:
            watermark_options['regions']=self.watermark_regions
        return normalize_job(dict(schema_version=1,output=dict(directory=self.output_edit.text(),fps=self.fps_spin.value() or None,
            audio_mode=self.audio_mode_combo.currentData()),
            clips=clips,boundaries=boundaries,independent_clips=self.independent_check.isChecked(),
            internal_motion=dict(reports=self.report_paths,selected_ids=selected,excluded_ids=excluded),
            narration={**{key:(field.text() or None) for key,field in self.narration_fields.items()},
                'subtitle_style':dict(font=self.subtitle_font.currentFont().family(),size=self.subtitle_size.value(),
                    font_path=self.subtitle_font_file.text() or None,
                    position='top' if self.subtitle_position.value()<34 else 'middle' if self.subtitle_position.value()<67 else 'bottom',
                    vertical_position=self.subtitle_position.value(),
                    alignment=self.subtitle_alignment.currentData(),margin=self.subtitle_margin.value(),
                    background=self.subtitle_background.isChecked(),
                    background_color=self.subtitle_background_color,
                    background_opacity=self.subtitle_background_opacity.value(),text_color=self.subtitle_color,
                    outline=self.subtitle_outline.isChecked(),outline_size=self.subtitle_outline_size.value(),
                    bold=self.subtitle_bold.isChecked())},
            enhancements=dict(interpolation=dict(enabled=self.interpolate_check.isChecked(),backend='cpu_flow'),
                stabilization=dict(enabled=self.stabilize_check.isChecked(),strength=self.stabilize_strength.value(),
                    smoothing_seconds=self.stabilize_smoothing.value(),max_crop_fraction=self.crop_percent.value()/100),
                watermark=watermark_options)),Path.cwd())

    def set_config(self,config):
        config=normalize_job(config,Path.cwd())
        motion=config['internal_motion']
        load_selections(motion['reports'],[SimpleNamespace(path=Path(c['path'])) for c in config['clips']],motion['selected_ids'],motion['excluded_ids'])
        self._master_json_path=None;self._master_json_data=None
        self._loading=True
        self.clip_table.setRowCount(0)
        for c in config['clips']:
            row=self.clip_table.rowCount();self.clip_table.insertRow(row)
            cells=[item(checked=c['correction_enabled']),item(c['id']),item(c['path']),item('Loading…',editable=False),
                   item(c['target_seconds']),item(c['protect_seconds']),item(c['max_speed']),item(c['ramp_seconds']),item('',editable=False)]
            for col,value in enumerate(cells):self.clip_table.setItem(row,col,value)
        self._refresh_ten_second_rows()
        self.output_edit.setText(config['output']['directory']);self.fps_spin.setValue(config['output']['fps'] or 0)
        self.independent_check.setChecked(config['independent_clips'])
        self.audio_mode_combo.setCurrentIndex(max(0,self.audio_mode_combo.findData(config['output']['audio_mode'])))
        for key,field in self.narration_fields.items():
            value=config['narration'].get(key)
            field.setText(value or '')
            field.setToolTip(value or 'Select a file. The full path is stored in the job JSON.')
        self._update_narration_summary()
        style=config['narration']['subtitle_style']
        if style['font_path']:
            self.subtitle_font_file.setText(style['font_path'])
            font_id=QFontDatabase.addApplicationFont(style['font_path'])
            if font_id>=0:self._subtitle_application_fonts.extend(QFontDatabase.applicationFontFamilies(font_id))
        else:self.subtitle_font_file.clear()
        self.subtitle_font.setCurrentFont(QFont(style['font']))
        self.subtitle_size.setValue(style['size'])
        vertical=style['vertical_position']
        self.subtitle_position.setValue(vertical)
        self._subtitle_position_changed(vertical)
        self.subtitle_alignment.setCurrentIndex(self.subtitle_alignment.findData(style['alignment']))
        self.subtitle_margin.setValue(style['margin']);self.subtitle_background.setChecked(style['background'])
        self.subtitle_background_opacity.setValue(style['background_opacity'])
        self._set_subtitle_background_color(style['background_color'])
        self._set_subtitle_color(style['text_color'])
        self.subtitle_outline.setChecked(style['outline']);self.subtitle_outline_size.setValue(style['outline_size'])
        self.subtitle_bold.setChecked(style['bold'])
        effects=config['enhancements'];s=effects['stabilization']
        self.interpolate_check.setChecked(effects['interpolation']['enabled']);self.stabilize_check.setChecked(s['enabled'])
        self.stabilize_strength.setValue(s['strength']);self.stabilize_smoothing.setValue(s['smoothing_seconds']);self.crop_percent.setValue(s['max_crop_fraction']*100)
        w=effects['watermark'];self.watermark_check.setChecked(w['enabled'])
        profile=w.get('profile','gemini')
        self.watermark_profile.setCurrentIndex(max(0,self.watermark_profile.findData(profile)))
        self.watermark_regions=[list(region) for region in w['regions']] if 'regions' in w else None
        self.mark_center_x.setValue(w['center_x_fraction']*100);self.mark_center_y.setValue(w['center_y_fraction']*100)
        self.mark_width.setValue(w['width_fraction']*100);self.mark_height.setValue(w['height_fraction']*100)
        self.sync_boundaries(config['boundaries']);self.report_paths=[];self.preview_paths={};self.preview_reasons={};self.motion_table.setRowCount(0)
        self.motion_summary.setText('No motion analysis loaded')
        motion=config['internal_motion']
        for path in motion['reports']:self.load_motion_report(path,motion['selected_ids'],motion['excluded_ids'])
        self.json_label.setText('Loaded JSON: none');self.json_preview.clear()
        self._loading=False;self.mark_dirty()
        for c in config['clips']:self.request_probe(c['path'])

    def load_json(self,path):
        try:data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError,ValueError) as exc:raise InputError(f'Cannot load JSON: {exc}') from exc
        if isinstance(data,dict) and 'records' in data and 'clips' not in data:
            paths=[self.clip_table.item(row,2).text() for row in range(self.clip_table.rowCount())]
            targets=load_master_timings(path,paths)
            self._loading=True
            try:
                for row,target in enumerate(targets):self.clip_table.item(row,4).setText(f'{target:g}')
            finally:self._loading=False
            self._refresh_ten_second_rows()
            self.mark_dirty()
            self.show_loaded_json(path,data,targets,'Master')
            self._master_json_path=Path(path).resolve();self._master_json_data=data
            self.state_label.setText(f'Master timings loaded for {len(targets)} clips · total {sum(targets):g}s · save job JSON before running')
            return 'Master'
        self.set_config(load_job(path))
        self.show_loaded_json(path,data,[c['target_seconds'] for c in data['clips']],'Job')
        return 'Job'
    def save_json(self,path,overwrite=False):return save_job(self.build_config(),path,overwrite=overwrite)

    def choose_narration_file(self,key,filters):
        current=self.narration_fields[key].text()
        path,_=QFileDialog.getOpenFileName(self,'Select narration file',current,filters)
        if not path:return
        selected=str(Path(path).resolve())
        self.narration_fields[key].setText(selected)
        self.narration_fields[key].setToolTip(selected)
        self._update_narration_summary();self.mark_dirty()

        if all(field.text() for field in self.narration_fields.values()) and self.clip_table.rowCount()>=2:
            self.guarded(self.check_narration_files)

    def check_narration_files(self):
        from ..narration import validate_narration
        config=self.build_config()
        plan=validate_narration(config['narration'],config['clips'])
        if plan is None:raise InputError('TTS 오디오, SRT, 샷 매핑 CSV를 먼저 선택하세요.')
        self.narration_summary.setText(
            f'검사 통과 · 자막 {plan["subtitle_count"]}개 / 샷 {plan["shot_count"]}개 · '
            f'TTS {plan["source_seconds"]:.2f}초 → 영상 {plan["duration"]:.2f}초 · '
            f'재생 속도 {plan["tempo"]:.4f}배 (음높이 유지). 문장별 발화 위치는 미검증입니다.')
        if self.subtitle_preview_start.value()==0 and plan['cues'][0]['start']>0:
            self.subtitle_preview_start.setValue(plan['cues'][0]['start'])
        return plan

    def clear_narration_file(self,key):
        self.narration_fields[key].clear()
        self.narration_fields[key].setToolTip('Select a file. The full path is stored in the job JSON.')
        self._update_narration_summary();self.mark_dirty()

    def _update_narration_summary(self):
        count=sum(bool(field.text()) for field in self.narration_fields.values())
        self.narration_summary.setText(f'{count} of {len(self.narration_fields)} files selected · Save JSON to keep these selections')

    def _schedule_subtitle_still(self,*_):
        if self._loading or not hasattr(self,'_subtitle_still_timer'):return
        if not self.narration_fields.get('subtitle_srt') or not self.narration_fields['subtitle_srt'].text():
            self.subtitle_still_status.setText('SRT 파일을 선택하면 현재 시각의 자막을 표시합니다.')
            self.subtitle_still_image.setPixmap(QPixmap());self.subtitle_still_image.setText('실시간 자막 미리보기')
            return
        if self.clip_table.rowCount()<2:
            self.subtitle_still_status.setText('미리보기를 위해 영상 클립 두 개 이상을 추가하세요.')
            return
        self._subtitle_still_timer.start()

    def _render_subtitle_still(self):
        try:
            config=self.build_config()
            self._subtitle_still_request+=1;request=self._subtitle_still_request
            output=Path(self._subtitle_still_temp.name)/f'subtitle-{request:06d}.png'
            worker=SubtitleStillThread(request,config,self.subtitle_preview_start.value(),output,self)
            self._subtitle_still_workers.append(worker)
            worker.rendered.connect(self._subtitle_still_done)
            worker.finished.connect(lambda w=worker:self._subtitle_still_finished(w))
            self.subtitle_still_status.setText('현재 시각의 자막 프레임을 업데이트하고 있습니다…')
            worker.start()
        except Exception as exc:self.subtitle_still_status.setText(f'미리보기를 만들 수 없습니다: {exc}')

    def _subtitle_still_done(self,request,path,error):
        if request!=self._subtitle_still_request:
            if path:Path(path).unlink(missing_ok=True)
            return
        if error:
            self.subtitle_still_status.setText(f'미리보기 오류: {error}')
            return
        pixmap=QPixmap(path)
        if pixmap.isNull():
            self.subtitle_still_status.setText('미리보기 이미지를 열 수 없습니다.')
            return
        self.subtitle_still_image.setPixmap(pixmap.scaled(
            self.subtitle_still_image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
        old=self._subtitle_still_path;self._subtitle_still_path=Path(path)
        if old and old!=self._subtitle_still_path:old.unlink(missing_ok=True)
        self.subtitle_still_status.setText(
            f'{self.subtitle_preview_start.value():.2f}초 프레임 · 자막 모양은 현재 설정을 반영합니다.')

    def _subtitle_still_finished(self,worker):
        if worker in self._subtitle_still_workers:self._subtitle_still_workers.remove(worker)

    def _set_subtitle_color(self,value):
        self.subtitle_color=value.upper()
        color_name={'#FFFFFF':'흰색','#FFFF00':'노랑','#000000':'검정'}.get(self.subtitle_color,self.subtitle_color)
        self.subtitle_color_button.setText(f'글자색: {color_name}')
        self.subtitle_color_button.setStyleSheet(f'background-color: {self.subtitle_color}; color: #555;')

    def _set_subtitle_background_color(self,value):
        self.subtitle_background_color=value.upper()
        color_name={'#000000':'검정','#111827':'차콜','#FFFFFF':'흰색'}.get(
            self.subtitle_background_color,self.subtitle_background_color)
        self.subtitle_background_color_button.setText(f'배경색: {color_name}')
        self.subtitle_background_color_button.setStyleSheet(
            f'background-color: {self.subtitle_background_color}; color: #777;')

    def _subtitle_position_changed(self,value):
        region='상단' if value<34 else '중앙' if value<67 else '하단'
        self.subtitle_position_label.setText(f'{value}% · {region}')

    def choose_subtitle_color(self):
        selected=QColorDialog.getColor(QColor(self.subtitle_color),self,'자막 글자색')
        if selected.isValid():self._set_subtitle_color(selected.name());self.mark_dirty()

    def choose_subtitle_background_color(self):
        selected=QColorDialog.getColor(QColor(self.subtitle_background_color),self,'자막 배경색')
        if selected.isValid():self._set_subtitle_background_color(selected.name());self.mark_dirty()

    def choose_subtitle_font_file(self):
        current=self.subtitle_font_file.text()
        path,_=QFileDialog.getOpenFileName(self,'자막 폰트 파일 추가',current,
                                            'Font files (*.ttf *.otf *.ttc)')
        if not path:return
        font_id=QFontDatabase.addApplicationFont(path)
        families=QFontDatabase.applicationFontFamilies(font_id) if font_id>=0 else []
        if not families:raise InputError('이 폰트 파일을 읽을 수 없습니다.')
        self._subtitle_application_fonts.extend(families)
        self.subtitle_font_file.setText(str(Path(path).resolve()))
        self.subtitle_font.setCurrentFont(QFont(families[0]))
        self.mark_dirty()

    def apply_subtitle_preset(self):
        presets={
            'general':dict(size=34,vertical_position=88,position='bottom',alignment='center',margin=48,
                background=False,background_color='#000000',background_opacity=55,
                text_color='#FFFFFF',outline=True,outline_size=2,bold=True),
            'black_soft':dict(size=34,vertical_position=88,position='bottom',alignment='center',margin=48,
                background=True,background_color='#000000',background_opacity=55,
                text_color='#FFFFFF',outline=False,outline_size=0,bold=True),
            'black_strong':dict(size=34,vertical_position=88,position='bottom',alignment='center',margin=48,
                background=True,background_color='#000000',background_opacity=78,
                text_color='#FFFFFF',outline=False,outline_size=0,bold=True),
            'white_box':dict(size=34,vertical_position=88,position='bottom',alignment='center',margin=48,
                background=True,background_color='#FFFFFF',background_opacity=88,
                text_color='#111111',outline=False,outline_size=0,bold=True),
            'documentary':dict(size=30,vertical_position=83,position='bottom',alignment='left',margin=60,
                background=True,background_color='#111827',background_opacity=68,
                text_color='#FFFFFF',outline=False,outline_size=0,bold=True),
            'yellow':dict(size=34,vertical_position=88,position='bottom',alignment='center',margin=48,
                background=False,background_color='#000000',background_opacity=55,
                text_color='#FFE66D',outline=True,outline_size=3,bold=True),
        }
        style=presets[self.subtitle_preset.currentData()]
        self._loading=True
        try:
            self.subtitle_size.setValue(style['size'])
            self.subtitle_position.setValue(style['vertical_position'])
            self._subtitle_position_changed(style['vertical_position'])
            self.subtitle_alignment.setCurrentIndex(self.subtitle_alignment.findData(style['alignment']))
            self.subtitle_margin.setValue(style['margin']);self.subtitle_background.setChecked(style['background'])
            self.subtitle_background_opacity.setValue(style['background_opacity'])
            self._set_subtitle_background_color(style['background_color'])
            self._set_subtitle_color(style['text_color']);self.subtitle_outline.setChecked(style['outline'])
            self.subtitle_outline_size.setValue(style['outline_size']);self.subtitle_bold.setChecked(style['bold'])
        finally:self._loading=False
        self.mark_dirty()

    def start_subtitle_preview(self):
        if self._subtitle_preview_thread and self._subtitle_preview_thread.isRunning():
            raise InputError('Subtitle sample is already rendering')
        config=self.build_config()
        if not all(config['narration'].get(key) for key in ('audio_path','subtitle_srt','shot_mapping_csv')):
            raise InputError('TTS 오디오, SRT, 샷 매핑 CSV를 먼저 선택하세요.')
        self.subtitle_preview_viewer.clear();self.subtitle_preview_open.setEnabled(False)
        if self._subtitle_preview_temp:self._subtitle_preview_temp.cleanup()
        self._subtitle_preview_temp=tempfile.TemporaryDirectory(prefix='video-manager-subtitle-preview-')
        output=Path(self._subtitle_preview_temp.name)/'subtitle_sample.mp4'
        self._subtitle_preview_thread=SubtitlePreviewThread(config,self.subtitle_preview_start.value(),output,self)
        self._subtitle_preview_thread.rendered.connect(self._subtitle_preview_done)
        self.subtitle_preview_button.setEnabled(False)
        self.subtitle_preview_status.setText('자막 샘플을 렌더링하고 있습니다…')
        self._subtitle_preview_thread.start()

    def _subtitle_preview_done(self,path,error):
        self.subtitle_preview_button.setEnabled(True)
        if error:
            self.subtitle_preview_status.setText(f'샘플 실패: {error}')
            return
        self._subtitle_preview_path=Path(path)
        self.subtitle_preview_viewer.load(path)
        self.subtitle_preview_open.setEnabled(True)
        self.subtitle_preview_status.setText('샘플 준비 완료 · 해당 샷 안에서 최대 5초입니다. 자막 스타일과 TTS를 확인하세요. 영상 속도·보정 효과는 최종 작업에서 적용됩니다.')
        self.tabs.setCurrentWidget(self.narration_page)

    def open_subtitle_preview(self):
        if not self._subtitle_preview_path or not self._subtitle_preview_path.is_file():
            raise InputError('Create a subtitle sample first')
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._subtitle_preview_path))):
            raise InputError('Could not open subtitle sample in the system player')

    def load_motion_report(self,path,selected=(),excluded=()):
        path=Path(path).resolve()
        clips=[SimpleNamespace(path=Path(self.clip_table.item(r,2).text()).resolve()) for r in range(self.clip_table.rowCount())]
        catalog,_=load_selections([path],clips,[],[])
        report=json.loads(path.read_text(encoding='utf-8'))
        loading=self._loading;self._loading=True
        if str(path) in self.report_paths:
            self._loading=loading;return
        self.report_paths.append(str(path))
        previews={p['region_id']:path.parent/p['comparison']['video'] for p in report.get('previews',[]) if p.get('comparison')}
        reasons={p['region_id']:p['reason'] for p in report.get('previews',[])}
        names={r['id']:Path(source['path']).name for source in report['sources'] for r in source['regions']}
        for identifier,entry in catalog.items():
            region=entry['region'];row=self.motion_table.rowCount();self.motion_table.insertRow(row)
            cells=[item(checked=identifier in selected),item(checked=identifier in excluded),item(identifier,editable=False),
                item(f"{names[identifier]} · {region['start_seconds']:.3f}–{region['end_seconds']:.3f}s",editable=False),
                item(', '.join(region['kinds']),editable=False),item(json.dumps(region['evidence'],ensure_ascii=False),editable=False),
                item(f"{region['confidence']:.0%}" if 'confidence' in region else 'Legacy / unknown',editable=False),
                item(reasons.get(identifier,region.get('review_reason','Legacy candidate; visual review required')),editable=False)]
            if region.get('analysis_version') and ('repeat_or_hold' in region['kinds'] or region.get('ambiguous_hold_overlap')):
                cells[0].setCheckState(Qt.Unchecked)
                cells[0].setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
                cells[0].setToolTip('Diagnostic only: an intentional stop cannot be distinguished from an erroneous hold.')
            for col,value in enumerate(cells):self.motion_table.setItem(row,col,value)
            if identifier in previews:self.preview_paths[identifier]=previews[identifier]
            self.preview_reasons[identifier]=reasons.get(identifier,region.get('review_reason','No rendered preview'))
        abstentions={}
        for source in report['sources']:
            for reason,count in source.get('diagnostics',{}).get('abstentions',{}).items():
                abstentions[reason]=abstentions.get(reason,0)+count
        summary=f"Last report: {report['version']} · {len(report['sources'])} clips · {len(catalog)} review regions · {len(previews)} previews. Nothing is selected automatically."
        if abstentions:summary+=' Deferred frame pairs: '+', '.join(f'{reason}={count}' for reason,count in sorted(abstentions.items()))
        self.motion_summary.setText(summary)
        self._loading=loading;self.mark_dirty()

    def clear_motion(self):
        self.report_paths=[];self.preview_paths={};self.preview_reasons={};self.motion_table.setRowCount(0)
        self.motion_summary.setText('No motion analysis loaded');self.mark_dirty()

    def preview_region(self,row):
        identifier=self.motion_table.item(row,2).text()
        if identifier not in self.preview_paths:self.state_label.setText(self.preview_reasons.get(identifier,'This report has no rendered preview; use Inspect motion'));return
        self.viewer.load(self.preview_paths[identifier]);self.tabs.setCurrentWidget(self.review_page)

    def _launch(self,arguments,kind,output):
        if self.process.state()!=QProcess.NotRunning:raise InputError('A job is already running')
        self._reset_live_previews()
        self._active_kind=kind;self._active_output=Path(output);self._active_revision=self.revision
        self._cancel_requested=False;self._worker_ready=False;self._worker_buffer="";self.log.clear()
        self._progress_buffer='';self._started_at=time.monotonic();self._stage_started=self._started_at
        self._stage='Preparing inputs';self._stage_done=0;self._stage_total=0
        self.work_timer.start();self._update_work_time()
        self.progress.setRange(0,0);self.run_button.setEnabled(False);self.cancel_button.setEnabled(False)
        self.state_label.setText(f'{kind}: starting worker…')
        self.process.setProgram(sys.executable);self.process.setArguments(['-m','video_manager.ui.worker',*arguments]);self.process.start()

    def start_job(self):
        config=self.build_config()
        if self.process.state()!=QProcess.NotRunning:raise InputError('A job is already running')
        if any(config['narration'].get(key) for key in ('audio_path','subtitle_srt','shot_mapping_csv')):
            self.check_narration_files()
        self._temporary=tempfile.TemporaryDirectory(prefix='video-manager-ui-')
        snapshot=Path(self._temporary.name)/'job.json';save_job(config,snapshot)
        self._launch(['run-job',str(snapshot)],'render',config['output']['directory'])

    def start_inspection(self):
        paths=[self.clip_table.item(r,2).text() for r in range(self.clip_table.rowCount())]
        if not paths:raise InputError('Add clips before inspection')
        output=Path(self.output_edit.text()).parent/f'motion-review-{uuid.uuid4().hex[:8]}'
        self._launch(['inspect-motion',*paths,'--output',str(output)],'inspect',output)

    def _read_process(self):
        data=bytes(self.process.readAllStandardOutput()).decode(errors='replace')
        self._progress_buffer=getattr(self,'_progress_buffer','')+data
        while '\n' in self._progress_buffer:
            line,self._progress_buffer=self._progress_buffer.split('\n',1)
            if line.startswith('VM_PROGRESS '):
                try:self._receive_progress(json.loads(line[len('VM_PROGRESS '):]))
                except (ValueError,KeyError,TypeError):self.log.appendPlainText(line)
            elif line.strip():self.log.appendPlainText(line.rstrip())
        self._worker_buffer=(getattr(self,'_worker_buffer','')+data)[-4000:]
        if 'WORKER_READY' in self._worker_buffer and not self._worker_ready:
            self._worker_ready=True;self.cancel_button.setEnabled(True)
            self.state_label.setText(f'{self._active_kind}: engine running')

    def _receive_progress(self,event):
        stage=str(event['stage']);done=float(event['done']);total=float(event['total'])
        if not all(math.isfinite(v) and v>=0 for v in (done,total)):raise ValueError
        if stage!=self._stage or done<self._stage_done:
            self._stage_started=time.monotonic()
        self._stage=stage;self._stage_done=done;self._stage_total=total
        if total:
            self.progress.setRange(0,1000);self.progress.setValue(min(1000,round(done/total*1000)))
            self.progress.setFormat('Current stage: %p%')
        else:self.progress.setRange(0,0)
        if self._active_kind=='render' and event.get('completed_video'):
            self._add_live_preview(event['completed_video'])
        self._update_work_time()

    def _reset_live_previews(self):
        self._live_preview_request+=1
        self.live_viewer.clear()
        if self._live_preview_copy:
            self._live_preview_copy.cleanup();self._live_preview_copy=None
        self.live_list.clear();self._live_preview_paths.clear()
        self.tabs.setTabText(self.tabs.indexOf(self.live_page),'Final / Live previews')
        self.live_status.setText('Waiting for a completed boundary comparison video.')

    def _add_live_preview(self,filename):
        path=Path(filename).resolve()
        root=self._active_output.resolve()
        if root not in path.parents:
            return
        if not path.name.startswith('comparison_boundary_') or path.suffix.lower()!='.mp4':
            return
        if not path.is_file():path=root/'results'/path.name
        if not path.is_file() or path.name in self._live_preview_paths:return
        try:number=int(path.stem.rsplit('_',1)[1])
        except ValueError:return
        self._live_preview_paths.add(path.name)
        self.live_list.addItem(f'Boundary {number:02d} · click to play')
        self.live_list.item(self.live_list.count()-1).setData(Qt.UserRole,str(path))
        count=self.live_list.count()
        self.tabs.setTabText(self.tabs.indexOf(self.live_page),f'Final / Live previews ({count})')
        self.live_status.setText(f'{count} completed comparison video(s). Click one to play it here.')

    def _add_final_video_preview(self,*,play=False):
        if self.result_dir is None:return
        path=self.result_dir/'results/corrected.mp4'
        if not path.is_file():return
        row=None
        for index in range(self.live_list.count()):
            if self.live_list.item(index).data(Qt.UserRole)==str(path):
                row=index;break
        if row is None:
            self.live_list.addItem('Final video · click to play')
            row=self.live_list.count()-1
            self.live_list.item(row).setData(Qt.UserRole,str(path))
        self.tabs.setTabText(self.tabs.indexOf(self.live_page),f'Final / Live previews ({self.live_list.count()})')
        self.live_status.setText('Final video is ready. Select it to play the completed result here.')
        if play:
            self.live_list.setCurrentRow(row)
            self.tabs.setCurrentWidget(self.live_page)

    def _live_preview_selected(self,current,previous):
        if current is None:return
        self._live_preview_request+=1
        request=self._live_preview_request
        source=Path(current.data(Qt.UserRole))
        if source.name=='corrected.mp4' and source.is_file():
            try:
                self.live_viewer.load(source)
                self.live_viewer.play()
                self.live_status.setText(f'{source.name} · completed video playing. Audio is available with “Play final video in system player”.')
            except Exception as exc:self.live_status.setText(f'Could not open final video: {exc}')
            return
        if not source.is_file():
            published=self._active_output/'results'/source.name
            if published.is_file():
                source=published
                current.setData(Qt.UserRole,str(source))
        if not source.is_file():
            self.live_status.setText(f'Comparison video not found: {source.name}')
            return
        temporary=tempfile.TemporaryDirectory(prefix='video-manager-live-preview-')
        worker=PreviewCopyThread(source,temporary,self)
        self._live_preview_workers.append(worker)
        worker.copied.connect(lambda error,w=worker,n=request:self._preview_copy_done(w,n,error))
        worker.finished.connect(lambda w=worker:self._live_preview_workers.remove(w))
        self.live_status.setText(f'Preparing {source.name} for playback…')
        worker.start()

    def _preview_copy_done(self,worker,request,error):
        if request!=self._live_preview_request:
            worker.temporary.cleanup();return
        if error:
            worker.temporary.cleanup();self.live_status.setText(f'Could not copy preview: {error}')
            return
        try:
            self.live_viewer.load(worker.copy)
            self.live_viewer.play()
        except Exception as exc:
            if self._live_preview_copy:
                self._live_preview_copy.cleanup();self._live_preview_copy=None
            worker.temporary.cleanup();self.live_status.setText(f'Could not open preview: {exc}')
            return
        old=self._live_preview_copy;self._live_preview_copy=worker.temporary
        if old:old.cleanup()
        self.live_status.setText(f'{worker.source.name} · playing; pause, seek, or step through frames.')

    def _relocate_live_previews(self):
        if not self._active_output:return
        for row in range(self.live_list.count()):
            entry=self.live_list.item(row)
            old=Path(entry.data(Qt.UserRole))
            published=self._active_output/'results'/old.name
            if published.is_file():entry.setData(Qt.UserRole,str(published))

    @staticmethod
    def _duration_text(seconds):
        seconds=max(0,int(seconds));hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

    def _update_work_time(self):
        if self._started_at is None:return
        now=time.monotonic();elapsed=now-self._started_at
        remaining='Calculating…'
        if self._stage_total and self._stage_done>0:
            estimate=(now-self._stage_started)*max(0,self._stage_total-self._stage_done)/self._stage_done
            remaining='~'+self._duration_text(estimate)
        self.time_label.setText(f'Elapsed: {self._duration_text(elapsed)} · {self._stage} · Stage remaining: {remaining}')

    def cancel_job(self):
        if self.process.state()==QProcess.NotRunning:return
        self._cancel_requested=True;self.cancel_button.setEnabled(False);self.state_label.setText('Cancelling · waiting for safe cleanup…')
        if os.name=='posix' and self._worker_ready:
            try:os.killpg(int(self.process.processId()),signal.SIGINT)
            except ProcessLookupError:pass
        else:self.process.terminate()

    def _process_error(self,error):
        self.state_label.setText(f'Worker error: {self.process.errorString()}')
        if error==QProcess.FailedToStart:self._finished(1,QProcess.CrashExit)

    def _finished(self,code,status):
        self.work_timer.stop()
        self._read_process();self.run_button.setEnabled(True);self.cancel_button.setEnabled(False);self.progress.setRange(0,1)
        self.progress.setFormat('%p%')
        if self._cancel_requested:
            state='cancelled';self.state_label.setText('Cancelled · partial files are not published as results');self.progress.setValue(0)
        elif code!=0:
            state='failed';self.state_label.setText(f'Failed (exit {code}) · see worker log');self.progress.setValue(0)
        else:
            state='success';self.progress.setValue(1)
            try:
                if self._active_kind=='inspect':
                    self.load_motion_report(self._active_output/'results/motion_report.json')
                    self.tabs.setCurrentWidget(self.motion_page)
                    self.state_label.setText('Inspection complete · review candidates in Internal motion, then Save JSON and Run job')
                else:
                    self._relocate_live_previews()
                    self.load_result(self._active_output)
                    self._add_final_video_preview(play=True)
                    self.result_revision=self._active_revision
                    if self.revision!=self.result_revision:self.state_label.setText('Render completed for earlier settings · result is stale')
            except Exception as exc:state='failed';self.state_label.setText(f'Result review failed: {exc}')
        if self._active_kind=='render' and state!='success' and self.live_list.count():
            self.live_status.setText('Job did not finish. These are completed previews, not a final result.')
        if self._temporary:self._temporary.cleanup();self._temporary=None
        if self._started_at is not None:
            self.time_label.setText(f'{state} · Elapsed: {self._duration_text(time.monotonic()-self._started_at)}')
        self.workerFinished.emit(state)

    def load_result(self,path):
        result_dir=Path(path)
        report=json.loads((result_dir/'results/report.json').read_text(encoding='utf-8'))
        self.result_dir=result_dir;self._result_report=report
        final_video=self.result_dir/'results/corrected.mp4'
        self.final_video_button.setEnabled(final_video.is_file())
        self.live_final_button.setEnabled(final_video.is_file())
        self._add_final_video_preview()
        self.viewer.clear()
        self.comparison_combo.clear()
        if final_video.is_file():
            self.comparison_combo.addItem('Final video · silent preview',str(final_video))
        for output in report.get('individual_outputs',[]):
            path=self.result_dir/'results'/output['file']
            if path.is_file():
                self.comparison_combo.addItem(
                    f"{output['clip_id']} · {output['measured_seconds']:.3f}s",str(path))
        for comp in report.get('comparisons',[]):self.comparison_combo.addItem(f"Boundary {comp['boundary']}",str(self.result_dir/'results'/comp['video']))
        if self.comparison_combo.count():self._comparison_changed(0)
        self.timeline_table.setRowCount(len(report.get('timeline',[])))
        for row,t in enumerate(report.get('timeline',[])):
            for col,value in enumerate([t['clip_id'],f"{t['start_seconds']:.3f}",f"{t['end_seconds']:.3f}",f"{t['measured_clip_seconds']:.6f}",f"{t['error_seconds']:+.6f}"]):
                self.timeline_table.setItem(row,col,item(value,editable=False))
        if report.get('timeline'):self.timeline_table.setCurrentCell(0,0);self.curve.set_model(report['timeline'][0]['mapping'])
        total=report.get('timeline_validation',{})
        effects=report.get('corrected',{}).get('enhancements',[])
        summaries=[]
        for entry in effects:
            reasons=entry.get('interpolation_reasons',{})
            skipped=sorted(((reason,count) for reason,count in reasons.items() if reason!='interpolated'),
                           key=lambda pair:pair[1],reverse=True)[:2]
            summary=(f"{entry['clip_id']}: interpolated {entry.get('interpolated_output_frames',0)} frames · "
                f"stabilized {entry.get('transformed_output_frames',0)} frames · "
                f"mark removed from {entry.get('watermark_removed_source_frames',0)} source frames · "
                f"{entry.get('stabilization',{}).get('reason',entry.get('reason',''))}")
            if skipped:summary+=' · interpolation skipped: '+', '.join(f'{reason} ({count})' for reason,count in skipped)
            summaries.append(summary)
        self.enhancement_summary.setPlainText('\n'.join(summaries));self.enhancement_summary.setVisible(bool(summaries))
        if report.get('independent_clips'):
            self.state_label.setText(f"Complete · {len(report.get('individual_outputs',[]))} separate videos · summed duration {total.get('measured_total_seconds',0):.6f}s · visual quality unconfirmed")
        else:
            self.state_label.setText(f"Complete · {total.get('measured_total_seconds',0):.6f}s · total error {total.get('error_seconds',0):+.6f}s · visual quality unconfirmed")
        self.tabs.setCurrentWidget(self.review_page)

    def _curve_changed(self,row,*_):
        if self._result_report and 0<=row<len(self._result_report.get('timeline',[])):self.curve.set_model(self._result_report['timeline'][row]['mapping'])

    def _comparison_changed(self,index):
        path=self.comparison_combo.itemData(index)
        if path:
            try:self.viewer.load(path)
            except Exception as exc:self.state_label.setText(str(exc))

    def open_results(self):
        if self.result_dir:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_dir)))

    def play_final_video(self):
        if self.result_dir is None:raise InputError('Load a completed result first')
        video=self.result_dir/'results/corrected.mp4'
        if not video.is_file():raise InputError(f'Final video is missing: {video}')
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(video.resolve()))):
            raise InputError(f'Could not open the final video: {video}')

    def open_enhancement_help(self):
        path=Path(__file__).with_name('video_enhancements_help.html').resolve()
        if not path.is_file():raise FileNotFoundError(f'Enhancement guide is missing: {path}')
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            raise RuntimeError(f'Could not open the enhancement guide: {path}')

    def choose_results(self):
        path=QFileDialog.getExistingDirectory(self,'Open a completed job folder')
        if path:
            self.load_result(path);self.result_revision=None
            self.state_label.setText(self.state_label.text()+' · loaded result; current settings not matched')

    def choose_clips(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add clips','','Video files (*.mp4 *.mov *.mkv *.webm);;All files (*)')
        for path in paths:self.add_clip(path)
    def choose_load(self):
        path,_=QFileDialog.getOpenFileName(self,'Load job or I2V Master timings','','JSON (*.json)')
        if not path:return
        kind=self.load_json(path)
        self._pending_save_path=None
        if kind=='Job':
            source=Path(path).expanduser().absolute()
            source.unlink()
            self._pending_save_path=source
            self.json_label.setText(self.json_label.text()+'\nSource job JSON deleted · Save JSON to recreate it')
            self.state_label.setText('Job loaded · source JSON deleted · Save JSON to write the new settings')
    def choose_save(self):
        suggested=str(self._pending_save_path) if self._pending_save_path else ''
        path,_=QFileDialog.getSaveFileName(self,'Save job',suggested,'JSON (*.json)')
        if path:
            self.save_json(path,overwrite=Path(path).exists())
            self._pending_save_path=None
    def choose_motion_report(self):
        path,_=QFileDialog.getOpenFileName(self,'Load motion report','','JSON (*.json)')
        if path:
            self.load_motion_report(path)
            self.tabs.setCurrentWidget(self.motion_page)

    def closeEvent(self,event):
        if self.process.state()!=QProcess.NotRunning:
            self.cancel_job();event.ignore();return
        if self._subtitle_preview_thread and self._subtitle_preview_thread.isRunning():
            event.ignore();self.subtitle_preview_status.setText('샘플 렌더링이 끝나면 창을 닫을 수 있습니다.');return
        if any(worker.isRunning() for worker in self._subtitle_still_workers):
            event.ignore();self.subtitle_still_status.setText('실시간 미리보기 프레임 렌더링이 끝나면 창을 닫을 수 있습니다.');return
        for worker in list(self.probers):worker.wait()
        self._live_preview_request+=1
        for worker in list(self._live_preview_workers):worker.wait()
        self.viewer.close();self.live_viewer.close();self.subtitle_preview_viewer.close()
        if self._subtitle_preview_temp:self._subtitle_preview_temp.cleanup();self._subtitle_preview_temp=None
        if self._live_preview_copy:self._live_preview_copy.cleanup();self._live_preview_copy=None
        for worker in list(self._live_preview_workers):worker.temporary.cleanup()
        if self._subtitle_still_temp:self._subtitle_still_temp.cleanup();self._subtitle_still_temp=None
        super().closeEvent(event)


def main():
    app=QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion');window=MainWindow();window.show()
    return app.exec()
