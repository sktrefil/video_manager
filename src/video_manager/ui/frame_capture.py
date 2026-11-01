"""Small desktop tool for saving a still frame from a video."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QFileDialog, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget, QCheckBox,
                               QSlider)


def _probe(path: Path) -> tuple[float, float]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe를 찾을 수 없습니다. FFmpeg를 설치하고 PATH에 추가하세요.")
    result = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=duration,avg_frame_rate",
                             "-show_entries", "format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "동영상 정보를 읽을 수 없습니다.")
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    rate = stream.get("avg_frame_rate", "30/1").split("/")
    fps = float(rate[0]) / float(rate[1]) if len(rate) == 2 and float(rate[1]) else 30.0
    if duration <= 0:
        raise RuntimeError("동영상 길이를 확인할 수 없습니다.")
    return duration, fps if fps > 0 else 30.0


def _extract(source: Path, seconds: float, destination: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg를 찾을 수 없습니다. FFmpeg를 설치하고 PATH에 추가하세요.")
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Some Windows FFmpeg builds silently fail to create image files at Unicode
    # output paths. Write to an ASCII temporary path, then let Python copy it.
    with tempfile.NamedTemporaryFile(prefix="vm_frame_",suffix=".png",dir=Path.cwd(),delete=False) as stream:
        temporary=Path(stream.name)
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                                 "-i", str(source), "-ss", f"{seconds:.6f}", "-map", "0:v:0", "-frames:v", "1",
                                 "-update", "1", str(temporary)], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
        if result.returncode or not temporary.is_file() or temporary.stat().st_size==0:
            detail = result.stderr.strip() or result.stdout.strip()
            if not detail:
                detail = f"FFmpeg 종료 코드: {result.returncode}; 임시 이미지 파일이 생성되지 않았습니다."
            raise RuntimeError(f"해당 시각의 프레임을 추출하지 못했습니다.\n{detail}")
        shutil.copyfile(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)


def _trim_video(source: Path, seconds: float, destination: Path) -> None:
    """Create an accurate MP4 from the start through the requested frame."""
    ffmpeg=shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg를 찾을 수 없습니다. FFmpeg를 설치하고 PATH에 추가하세요.")
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="vm_trim_",suffix=".mp4",dir=Path.cwd(),delete=False) as stream:
        temporary=Path(stream.name)
    try:
        result=subprocess.run([ffmpeg,"-hide_banner","-loglevel","warning","-y","-i",str(source),
            "-t",f"{seconds:.6f}","-map","0:v:0","-map","0:a?","-c:v","libx264",
            "-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-c:a","aac",
            "-b:a","192k","-movflags","+faststart",str(temporary)],capture_output=True,text=True,
            encoding="utf-8",errors="replace")
        if result.returncode or not temporary.is_file() or temporary.stat().st_size==0:
            detail=result.stderr.strip() or result.stdout.strip()
            if not detail:
                detail=f"FFmpeg 종료 코드: {result.returncode}; 잘라낸 영상 파일이 생성되지 않았습니다."
            raise RuntimeError(f"잘라낸 영상 저장에 실패했습니다.\n{detail}")
        shutil.copyfile(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)


class Task(QThread):
    done = Signal(object)

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def run(self):
        try:
            self.done.emit((True, self.callback()))
        except Exception as exc:
            self.done.emit((False, str(exc)))


class TimelineSlider(QSlider):
    """Timeline slider whose click position is mapped directly to time."""
    seeked=Signal(int)

    def __init__(self,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent)
        self.setTracking(True)

    def _seek_from_x(self,x):
        span=max(1,self.width()-16)
        fraction=min(1.,max(0.,(x-8)/span))
        value=self.minimum()+round(fraction*(self.maximum()-self.minimum()))
        self.setValue(value)
        self.seeked.emit(value)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.setSliderDown(True)
            self._seek_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self.isSliderDown():
            self._seek_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.isSliderDown():
            self._seek_from_x(event.position().x())
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class FrameCaptureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("동영상 프레임 이미지 저장")
        self.resize(1000, 760)
        self.setAcceptDrops(True)
        self.source: Path | None = None
        self.duration = 0.0
        self.fps = 30.0
        self._max_seek_time=0.0
        self._syncing_position=False
        self._task: Task | None = None
        self._saving = False

        root = QWidget()
        layout = QVBoxLayout(root)
        controls = QHBoxLayout()
        self.choose = QPushButton("동영상 열기")
        self.choose.clicked.connect(self.open_video)
        self.drop_hint = QLabel("동영상을 여기에 드래그하세요")
        self.drop_hint.setStyleSheet("color:#666; padding:6px")
        controls.addWidget(self.choose)
        controls.addWidget(self.drop_hint, 1)
        layout.addLayout(controls)

        self.preview = QVideoWidget()
        self.preview.setMinimumSize(640, 400)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#20242b; color:#cbd0d8; border:1px solid #444")
        layout.addWidget(self.preview, 1)

        playback=QHBoxLayout()
        self.play_button=QPushButton("재생")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_playback)
        playback.addWidget(self.play_button)
        self.timeline=TimelineSlider()
        self.timeline.setRange(0,0)
        self.timeline.setEnabled(False)
        self.timeline.seeked.connect(self.seek_to_position)
        playback.addWidget(self.timeline,1)
        self.position_label=QLabel("00:00.000 / 00:00.000")
        playback.addWidget(self.position_label)
        layout.addLayout(playback)

        self.player=QMediaPlayer(self)
        self.audio_output=QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.preview)
        self.player.positionChanged.connect(self._player_position_changed)
        self.player.durationChanged.connect(self._player_duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._playback_error)

        form = QFormLayout()
        self.time = QDoubleSpinBox()
        self.time.setRange(0, 86400)
        self.time.setDecimals(3)
        self.time.setSuffix(" 초")
        self.time.setValue(10)
        self.time.valueChanged.connect(self._time_changed)
        form.addRow("캡처 시각", self.time)
        self.trim_check=QCheckBox("지정 시각까지 자른 영상도 함께 저장")
        self.trim_check.setToolTip("처음부터 지정 시각의 캡처 프레임까지 MP4로 저장합니다. 정확한 컷을 위해 영상은 재인코딩되며 원본 오디오가 있으면 함께 저장합니다.")
        form.addRow("추가 저장",self.trim_check)
        self.filename = QLineEdit("frame.png")
        form.addRow("저장 파일명", self.filename)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("비워두면 동영상이 있는 폴더에 저장합니다")
        browse = QPushButton("폴더 선택")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("저장 폴더", folder_row)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.status = QLabel("동영상을 열거나 이 창으로 드래그하세요.")
        self.save = QPushButton("이미지 저장")
        self.save.setEnabled(False)
        self.save.clicked.connect(self.save_image)
        actions.addWidget(self.status, 1)
        actions.addWidget(self.save)
        layout.addLayout(actions)
        self.setCentralWidget(root)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self.load_video(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(self, "동영상 선택", "",
                    "동영상 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;모든 파일 (*)")
        if path:
            self.load_video(Path(path))

    def load_video(self, path: Path):
        if not path.is_file():
            QMessageBox.warning(self, "파일 오류", "선택한 파일을 찾을 수 없습니다.")
            return
        self.source = path
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self.filename.setText(f"{path.stem}_frame.png")
        self.folder.clear()
        self.drop_hint.setText(str(path))
        self.status.setText("동영상 정보를 확인하는 중…")
        self.save.setEnabled(False)
        self._start(lambda: _probe(path), self._on_probe)

    def _start(self, callback, handler):
        if self._task and self._task.isRunning():
            return
        self._task = Task(callback)
        self._task.done.connect(handler)
        self._task.start()

    def _on_probe(self, result):
        ok, value = result
        if not ok:
            self.status.setText("정보를 읽지 못했습니다.")
            QMessageBox.warning(self, "동영상 확인 실패", value)
            return
        self.duration, self.fps = value
        self._max_seek_time=max(0,self.duration-1.5/self.fps)
        self.time.setRange(0,self._max_seek_time)
        self.timeline.setRange(0,round(self._max_seek_time*1000))
        self.timeline.setEnabled(True)
        self.play_button.setEnabled(True)
        self._syncing_position=True
        self.time.setValue(min(10,self._max_seek_time))
        self._syncing_position=False
        self.player.setPosition(round(self.time.value()*1000))
        self.save.setEnabled(True)
        self.status.setText(f"길이 {self.duration:.2f}초 · 재생하거나 타임라인을 클릭해 캡처 지점을 고르세요.")

    def update_preview(self, *_):
        if not self.source or not self.save.isEnabled():
            return
        if self._task and self._task.isRunning():
            self._preview_pending = True
            return
        seconds = min(self.time.value(), max(0, self.duration - 1.5 / self.fps))
        preview_path = Path(self._temp.name) / "preview.png"
        self.status.setText(f"{self.time.value():.3f}초 프레임 미리보기 생성 중…")
        if not self._saving:
            self.save.setEnabled(False)
        self._start(lambda: (_extract(self.source, seconds, preview_path), preview_path)[1], self._on_preview)

    def _on_preview(self, result):
        ok, value = result
        if not self._saving:
            self.save.setEnabled(True)
        if not ok:
            self.status.setText("미리보기를 만들지 못했습니다.")
            self._run_pending_preview()
            return
        pixmap = QPixmap(str(value))
        if pixmap.isNull():
            self.status.setText("미리보기 이미지를 열 수 없습니다.")
            self._run_pending_preview()
            return
        self.preview.setPixmap(pixmap.scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        self.status.setText(f"{self.time.value():.3f}초 프레임 미리보기")
        self._run_pending_preview()

    def _run_pending_preview(self):
        if self._preview_pending:
            self._preview_pending = False
            QTimer.singleShot(0, self.update_preview)

    @staticmethod
    def _format_time(milliseconds):
        milliseconds=max(0,int(milliseconds))
        minutes,remaining=divmod(milliseconds,60000)
        seconds,millis=divmod(remaining,1000)
        return f"{minutes:02d}:{seconds:02d}.{millis:03d}"

    def _player_duration_changed(self,milliseconds):
        if milliseconds>0:
            self.position_label.setText(f"{self._format_time(self.player.position())} / {self._format_time(milliseconds)}")

    def _player_position_changed(self,milliseconds):
        safe_ms=min(milliseconds,round(self._max_seek_time*1000))
        self._syncing_position=True
        self.timeline.setValue(safe_ms)
        self.time.setValue(safe_ms/1000)
        self._syncing_position=False
        self.position_label.setText(f"{self._format_time(milliseconds)} / {self._format_time(self.player.duration())}")

    def _time_changed(self,seconds):
        if self._syncing_position or not self.source:
            return
        milliseconds=round(min(seconds,self._max_seek_time)*1000)
        self._syncing_position=True
        self.timeline.setValue(milliseconds)
        self._syncing_position=False
        self.player.setPosition(milliseconds)

    def seek_to_position(self,milliseconds):
        if self._syncing_position or not self.source:
            return
        milliseconds=min(milliseconds,round(self._max_seek_time*1000))
        self._syncing_position=True
        self.time.setValue(milliseconds/1000)
        self.timeline.setValue(milliseconds)
        self._syncing_position=False
        self.player.setPosition(milliseconds)

    def toggle_playback(self):
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.position()>=round(self._max_seek_time*1000):
                self.player.setPosition(0)
            self.player.play()

    def _playback_state_changed(self,state):
        self.play_button.setText("일시정지" if state==QMediaPlayer.PlaybackState.PlayingState else "재생")

    def _playback_error(self,error,_error_string):
        if error!=QMediaPlayer.Error.NoError:
            self.status.setText(f"영상 재생 오류: {self.player.errorString()}")

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.folder.text() or str(self.source.parent if self.source else Path.home()))
        if folder:
            self.folder.setText(folder)

    def save_image(self):
        if not self.source:
            return
        if self._task and self._task.isRunning():
            self.status.setText("미리보기 생성이 끝난 뒤 저장할 수 있습니다.")
            return
        name = self.filename.text().strip()
        if not name:
            QMessageBox.warning(self, "파일명 확인", "저장 파일명을 입력하세요.")
            return
        target = Path(self.folder.text().strip() or self.source.parent) / name
        if target.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            target = target.with_suffix(".png")
        seconds = min(self.time.value(), max(0, self.duration - 1.5 / self.fps))
        video_target=None
        if self.trim_check.isChecked():
            if seconds<=0:
                QMessageBox.warning(self,"자르기 시각 확인","영상 저장을 선택하려면 캡처 시각을 0초보다 크게 지정하세요.")
                return
            cut_duration=min(self.duration,seconds+1.5/self.fps)
            video_target=target.parent/f"{self.source.stem}_to_{seconds:.3f}s.mp4"
        conflicts=[path for path in (target,video_target) if path is not None and path.exists()]
        if conflicts:
            answer = QMessageBox.question(self, "덮어쓰기 확인", "이미 파일이 있습니다. 덮어쓸까요?\n"+"\n".join(map(str,conflicts)),
                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.save.setEnabled(False)
        self._saving = True
        self.status.setText("이미지를 저장하는 중…")
        def save_outputs():
            target.parent.mkdir(parents=True,exist_ok=True)
            if video_target is not None:
                _trim_video(self.source,cut_duration,video_target)
            _extract(self.source,seconds,target)
            return (target,video_target) if video_target is not None else (target,)
        self._start(save_outputs,self._on_saved)

    def _on_saved(self, result):
        ok, value = result
        self._saving = False
        self.save.setEnabled(True)
        if not ok:
            self.status.setText("저장에 실패했습니다.")
            QMessageBox.critical(self, "저장 실패", value)
            return
        self.status.setText(f"저장 완료: {value[0]}")
        QMessageBox.information(self, "저장 완료", "저장했습니다.\n"+"\n".join(map(str,value)))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = FrameCaptureWindow()
    window.show()
    return app.exec()


if __name__=='__main__':
    raise SystemExit(main())
