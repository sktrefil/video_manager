"""Desktop workflow built on the same strict job schema and process-based engine."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from types import SimpleNamespace
import uuid

from PySide6.QtCore import Qt,QThread,Signal,QProcess,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QTabWidget,
    QTableWidget,QTableWidgetItem,QPushButton,QLabel,QLineEdit,QDoubleSpinBox,QFileDialog,QMessageBox,
    QProgressBar,QPlainTextEdit,QComboBox,QHeaderView)

from ..errors import InputError
from ..internal_motion import load_selections
from ..job_schema import load_job,normalize_job,save_job
from ..probe import probe
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
        self.report_paths=[];self.preview_paths={};self.probers=[];self._temporary=None
        self._cancel_requested=False;self._worker_ready=False;self._active_output=None
        root=QWidget();self.setCentralWidget(root);layout=QVBoxLayout(root)
        toolbar=QHBoxLayout();layout.addLayout(toolbar)
        for label,callback in [('Load JSON',self.choose_load),('Save JSON',self.choose_save),
                               ('Add clips',self.choose_clips),('Inspect motion',self.start_inspection),
                               ('Load motion report',self.choose_motion_report),('Clear motion',self.clear_motion),('Load results',self.choose_results)]:
            button=QPushButton(label);button.clicked.connect(lambda _=False,fn=callback:self.guarded(fn));toolbar.addWidget(button)
        self.run_button=QPushButton('Run job');self.run_button.clicked.connect(lambda:self.guarded(self.start_job));toolbar.addWidget(self.run_button)
        self.cancel_button=QPushButton('Cancel');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel_job);toolbar.addWidget(self.cancel_button)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        clip_page=QWidget();cl=QVBoxLayout(clip_page);self.tabs.addTab(clip_page,'Clips & timing')
        self.clip_table=QTableWidget(0,8);self.clip_table.setHorizontalHeaderLabels(['Enabled','ID','Path','Source seconds','Target','Protect','Max speed','Ramp'])
        self.clip_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch);cl.addWidget(self.clip_table)
        row=QHBoxLayout();cl.addLayout(row)
        for label,fn in [('Remove',self.remove_clip),('Move up',lambda:self.move_clip(-1)),('Move down',lambda:self.move_clip(1))]:
            button=QPushButton(label);button.clicked.connect(fn);row.addWidget(button)
        row.addWidget(QLabel('Output directory'))
        self.output_edit=QLineEdit(str(Path.cwd()/'outputs'/f'ui-job-{uuid.uuid4().hex[:8]}'));row.addWidget(self.output_edit,1)
        self.fps_spin=QDoubleSpinBox();self.fps_spin.setRange(0,120);self.fps_spin.setDecimals(9);self.fps_spin.setSpecialValueText('First source FPS');row.addWidget(self.fps_spin)
        self.boundary_table=QTableWidget(0,7);self.boundary_table.setHorizontalHeaderLabels(['From','To','Enabled','Window','Strength','Local speed','Duplicate policy'])
        self.boundary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);self.tabs.addTab(self.boundary_table,'Boundaries')
        motion_page=QWidget();ml=QVBoxLayout(motion_page);self.tabs.addTab(motion_page,'Internal motion')
        ml.addWidget(QLabel('Suspicion candidates only. Unselected by default; exclusion wins. Double-click a row to preview.'))
        self.motion_table=QTableWidget(0,6);self.motion_table.setHorizontalHeaderLabels(['Select','Exclude','Region ID','Source range','Kinds','Evidence'])
        self.motion_table.horizontalHeader().setSectionResizeMode(5,QHeaderView.Stretch);ml.addWidget(self.motion_table)
        review_page=QWidget();rl=QVBoxLayout(review_page);self.tabs.addTab(review_page,'Review & results')
        self.comparison_combo=QComboBox();rl.addWidget(self.comparison_combo)
        self.viewer=ComparisonViewer();rl.addWidget(self.viewer,1)
        self.timeline_table=QTableWidget(0,5);self.timeline_table.setHorizontalHeaderLabels(['Clip','Start','End','Measured seconds','Error'])
        self.timeline_table.setMaximumHeight(130);rl.addWidget(self.timeline_table)
        self.curve=SpeedPlot();rl.addWidget(self.curve)
        open_button=QPushButton('Open result folder');open_button.clicked.connect(self.open_results);rl.addWidget(open_button)
        self.state_label=QLabel('Ready · output audio is muted');layout.addWidget(self.state_label)
        self.progress=QProgressBar();self.progress.setRange(0,1);self.progress.setValue(0);layout.addWidget(self.progress)
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
        self.comparison_combo.currentIndexChanged.connect(self._comparison_changed)
        self.timeline_table.currentCellChanged.connect(self._curve_changed)
        self._result_report=None

    def guarded(self,callback):
        try:return callback()
        except Exception as exc:
            self.state_label.setText(f'Error: {exc}');QMessageBox.warning(self,'Video Manager',str(exc))

    def mark_dirty(self,*_):
        if self._loading:return
        self.revision+=1
        if self.result_dir:self.state_label.setText('Settings changed · previous result is stale; rerun to refresh')
        elif self.process.state()==QProcess.NotRunning:self.state_label.setText('Settings changed · ready to validate and run')

    def _clip_changed(self,row,column):
        if self._loading:return
        self.mark_dirty()
        if column in [0,1,2]:self.sync_boundaries()
        if column==2 and self.clip_table.item(row,column):self.request_probe(self.clip_table.item(row,column).text())

    def add_clip(self,path):
        existing={self.clip_table.item(r,1).text() for r in range(self.clip_table.rowCount())}
        index=1
        while f'clip_{index:02d}' in existing:index+=1
        self._loading=True;row=self.clip_table.rowCount();self.clip_table.insertRow(row)
        values=[item(checked=True),item(f'clip_{index:02d}'),item(str(Path(path).resolve())),item('Loading…',editable=False),item(''),item('1'),item('12'),item('0.5')]
        for col,value in enumerate(values):self.clip_table.setItem(row,col,value)
        self._loading=False;self.sync_boundaries();self.mark_dirty();self.request_probe(str(Path(path).resolve()))

    def request_probe(self,path):
        worker=ProbeThread(path,self);self.probers.append(worker);worker.result.connect(self._probed)
        worker.finished.connect(lambda:self._probe_finished(worker));worker.start()

    def _probe_finished(self,worker):
        if worker in self.probers:self.probers.remove(worker)
        worker.deleteLater()

    def _probed(self,path,data):
        self._loading=True
        for row in range(self.clip_table.rowCount()):
            if self.clip_table.item(row,2).text()==path:
                self.clip_table.item(row,3).setText('Error' if 'error' in data else f"{data['duration']:.6f}")
                if not self.clip_table.item(row,4).text() and 'duration' in data:self.clip_table.item(row,4).setText(f"{data['duration']:.6f}")
        self._loading=False
        if 'error' in data:self.state_label.setText(data['error'])

    def remove_clip(self):
        row=self.clip_table.currentRow()
        if row>=0:self.clip_table.removeRow(row);self.sync_boundaries();self.mark_dirty()

    def move_clip(self,delta):
        row=self.clip_table.currentRow();other=row+delta
        if not 0<=other<self.clip_table.rowCount():return
        self._loading=True
        for column in range(self.clip_table.columnCount()):
            first=self.clip_table.takeItem(row,column);second=self.clip_table.takeItem(other,column)
            self.clip_table.setItem(row,column,second);self.clip_table.setItem(other,column,first)
        self.clip_table.setCurrentCell(other,1);self._loading=False;self.sync_boundaries();self.mark_dirty()

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
        return normalize_job(dict(schema_version=1,output=dict(directory=self.output_edit.text(),fps=self.fps_spin.value() or None,audio_mode='mute'),
            clips=clips,boundaries=boundaries,internal_motion=dict(reports=self.report_paths,selected_ids=selected,excluded_ids=excluded)),Path.cwd())

    def set_config(self,config):
        config=normalize_job(config,Path.cwd())
        motion=config['internal_motion']
        load_selections(motion['reports'],[SimpleNamespace(path=Path(c['path'])) for c in config['clips']],motion['selected_ids'],motion['excluded_ids'])
        self._loading=True
        self.clip_table.setRowCount(0)
        for c in config['clips']:
            row=self.clip_table.rowCount();self.clip_table.insertRow(row)
            cells=[item(checked=c['correction_enabled']),item(c['id']),item(c['path']),item('Loading…',editable=False),
                   item(c['target_seconds']),item(c['protect_seconds']),item(c['max_speed']),item(c['ramp_seconds'])]
            for col,value in enumerate(cells):self.clip_table.setItem(row,col,value)
        self.output_edit.setText(config['output']['directory']);self.fps_spin.setValue(config['output']['fps'] or 0)
        self.sync_boundaries(config['boundaries']);self.report_paths=[];self.preview_paths={};self.motion_table.setRowCount(0)
        motion=config['internal_motion']
        for path in motion['reports']:self.load_motion_report(path,motion['selected_ids'],motion['excluded_ids'])
        self._loading=False;self.mark_dirty()
        for c in config['clips']:self.request_probe(c['path'])

    def load_json(self,path):self.set_config(load_job(path))
    def save_json(self,path,overwrite=False):return save_job(self.build_config(),path,overwrite=overwrite)

    def load_motion_report(self,path,selected=(),excluded=()):
        path=Path(path).resolve()
        clips=[SimpleNamespace(path=Path(self.clip_table.item(r,2).text()).resolve()) for r in range(self.clip_table.rowCount())]
        catalog,_=load_selections([path],clips,[],[])
        report=json.loads(path.read_text())
        loading=self._loading;self._loading=True
        if str(path) in self.report_paths:
            self._loading=loading;return
        self.report_paths.append(str(path))
        previews={p['region_id']:path.parent/p['comparison']['video'] for p in report.get('previews',[])}
        names={r['id']:Path(source['path']).name for source in report['sources'] for r in source['regions']}
        for identifier,entry in catalog.items():
            region=entry['region'];row=self.motion_table.rowCount();self.motion_table.insertRow(row)
            cells=[item(checked=identifier in selected),item(checked=identifier in excluded),item(identifier,editable=False),
                item(f"{names[identifier]} · {region['start_seconds']:.3f}–{region['end_seconds']:.3f}s",editable=False),
                item(', '.join(region['kinds']),editable=False),item(json.dumps(region['evidence'],ensure_ascii=False),editable=False)]
            for col,value in enumerate(cells):self.motion_table.setItem(row,col,value)
            if identifier in previews:self.preview_paths[identifier]=previews[identifier]
        self._loading=loading;self.mark_dirty()

    def clear_motion(self):
        self.report_paths=[];self.preview_paths={};self.motion_table.setRowCount(0);self.mark_dirty()

    def preview_region(self,row):
        identifier=self.motion_table.item(row,2).text()
        if identifier not in self.preview_paths:self.state_label.setText('This report has no rendered preview; use Inspect motion');return
        self.viewer.load(self.preview_paths[identifier]);self.tabs.setCurrentIndex(3)

    def _launch(self,arguments,kind,output):
        if self.process.state()!=QProcess.NotRunning:raise InputError('A job is already running')
        self._active_kind=kind;self._active_output=Path(output);self._active_revision=self.revision
        self._cancel_requested=False;self._worker_ready=False;self._worker_buffer="";self.log.clear()
        self.progress.setRange(0,0);self.run_button.setEnabled(False);self.cancel_button.setEnabled(False)
        self.state_label.setText(f'{kind}: starting worker…')
        self.process.setProgram(sys.executable);self.process.setArguments(['-m','video_manager.ui.worker',*arguments]);self.process.start()

    def start_job(self):
        config=self.build_config()
        if self.process.state()!=QProcess.NotRunning:raise InputError('A job is already running')
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
        self.log.appendPlainText(data.rstrip())
        self._worker_buffer=(getattr(self,'_worker_buffer','')+data)[-4000:]
        if 'WORKER_READY' in self._worker_buffer and not self._worker_ready:
            self._worker_ready=True;self.cancel_button.setEnabled(True)
            self.state_label.setText(f'{self._active_kind}: engine running · progress is indeterminate')

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
        self._read_process();self.run_button.setEnabled(True);self.cancel_button.setEnabled(False);self.progress.setRange(0,1)
        if self._cancel_requested:
            state='cancelled';self.state_label.setText('Cancelled · partial files are not published as results');self.progress.setValue(0)
        elif code!=0:
            state='failed';self.state_label.setText(f'Failed (exit {code}) · see worker log');self.progress.setValue(0)
        else:
            state='success';self.progress.setValue(1)
            try:
                if self._active_kind=='inspect':
                    self.load_motion_report(self._active_output/'results/motion_report.json')
                    self.state_label.setText('Inspection complete · proposals remain unselected')
                else:
                    self.load_result(self._active_output)
                    self.result_revision=self._active_revision
                    if self.revision!=self.result_revision:self.state_label.setText('Render completed for earlier settings · result is stale')
            except Exception as exc:state='failed';self.state_label.setText(f'Result review failed: {exc}')
        if self._temporary:self._temporary.cleanup();self._temporary=None
        self.workerFinished.emit(state)

    def load_result(self,path):
        self.result_dir=Path(path);report=json.loads((self.result_dir/'results/report.json').read_text());self._result_report=report
        self.comparison_combo.clear()
        for comp in report.get('comparisons',[]):self.comparison_combo.addItem(f"Boundary {comp['boundary']}",str(self.result_dir/'results'/comp['video']))
        self.timeline_table.setRowCount(len(report.get('timeline',[])))
        for row,t in enumerate(report.get('timeline',[])):
            for col,value in enumerate([t['clip_id'],f"{t['start_seconds']:.3f}",f"{t['end_seconds']:.3f}",f"{t['measured_clip_seconds']:.6f}",f"{t['error_seconds']:+.6f}"]):
                self.timeline_table.setItem(row,col,item(value,editable=False))
        if report.get('timeline'):self.timeline_table.setCurrentCell(0,0);self.curve.set_model(report['timeline'][0]['mapping'])
        total=report.get('timeline_validation',{})
        self.state_label.setText(f"Complete · {total.get('measured_total_seconds',0):.6f}s · total error {total.get('error_seconds',0):+.6f}s · visual quality unconfirmed")
        self.tabs.setCurrentIndex(3)

    def _curve_changed(self,row,*_):
        if self._result_report and 0<=row<len(self._result_report.get('timeline',[])):self.curve.set_model(self._result_report['timeline'][row]['mapping'])

    def _comparison_changed(self,index):
        path=self.comparison_combo.itemData(index)
        if path:
            try:self.viewer.load(path)
            except Exception as exc:self.state_label.setText(str(exc))

    def open_results(self):
        if self.result_dir:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_dir)))

    def choose_results(self):
        path=QFileDialog.getExistingDirectory(self,'Open a completed job folder')
        if path:
            self.load_result(path);self.result_revision=None
            self.state_label.setText(self.state_label.text()+' · loaded result; current settings not matched')

    def choose_clips(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add clips','','Video files (*.mp4 *.mov *.mkv *.webm);;All files (*)')
        for path in paths:self.add_clip(path)
    def choose_load(self):
        path,_=QFileDialog.getOpenFileName(self,'Load job','','JSON (*.json)')
        if path:self.load_json(path)
    def choose_save(self):
        path,_=QFileDialog.getSaveFileName(self,'Save job','','JSON (*.json)')
        if path:self.save_json(path,overwrite=Path(path).exists())
    def choose_motion_report(self):
        path,_=QFileDialog.getOpenFileName(self,'Load motion report','','JSON (*.json)')
        if path:self.load_motion_report(path)

    def closeEvent(self,event):
        if self.process.state()!=QProcess.NotRunning:
            self.cancel_job();event.ignore();return
        for worker in list(self.probers):worker.wait()
        self.viewer.close();super().closeEvent(event)


def main():
    app=QApplication.instance() or QApplication(sys.argv)
    app.setStyle('Fusion');window=MainWindow();window.show()
    return app.exec()
