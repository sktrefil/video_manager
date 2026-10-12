import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt,QTimer,QProcess
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fixtures'))
from synthetic import make_motion_clip,make_positions_clip
from video_manager.errors import InputError
from video_manager.internal_motion import analyze_sources
from video_manager.job_schema import normalize_job,load_job
from video_manager.probe import probe
from video_manager.report import write_report
from video_manager.ui.app import MainWindow

APP=QApplication.instance() or QApplication([])


def wait_until(predicate,timeout=30000):
    end=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<end:QTest.qWait(20)
    if not predicate():raise AssertionError('Timed out waiting for UI condition')


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.window=MainWindow();self.window.show();QTest.qWait(20)
    def tearDown(self):
        if self.window.process.state()!=QProcess.NotRunning:
            self.window.cancel_job();wait_until(lambda:self.window.process.state()==QProcess.NotRunning)
        wait_until(lambda:not self.window.probers)
        self.window.close();APP.processEvents();self.tmp.cleanup()
    def config(self,count=40):
        paths=[make_motion_clip(self.root/f'clip{i}.mp4',5+i*30,35+i*30,count=count) for i in range(2)]
        return normalize_job(dict(schema_version=1,output=dict(directory=str(self.root/'result'),fps=20),
            clips=[dict(id=f'shot{i}',path=str(p),target_seconds=count/20,protect_seconds=.3,max_speed=9,ramp_seconds=.2) for i,p in enumerate(paths)]),self.root)

    def test_stretched_speed_plot_draws_deceleration(self):
        from video_manager.ui.viewer import SpeedPlot
        plot=SpeedPlot();plot.resize(500,160)
        plot.set_model(dict(output_last_display_seconds=119/24,peak_speed=1,
            terminal_speed=.730337,protect_seconds=1,ramp_seconds=.5,
            compressed=False,stretched=True))
        plot.show();QTest.qWait(20)
        rendered=plot.grab().toImage()
        def curve_y(x):
            rows=[y for y in range(25,135) if rendered.pixelColor(x,y).name()=='#2767ac']
            self.assertTrue(rows)
            return sum(rows)/len(rows)
        self.assertGreater(curve_y(450),curve_y(50)+20)
        plot.close()

    def test_master_json_fills_targets_and_preserves_local_paths(self):
        paths=[make_motion_clip(self.root/name,5+i*30,35+i*30,count=100)
               for i,name in enumerate(['01_02.mp4','01_03.mp4'])]
        for path in paths:self.window.add_clip(path)
        wait_until(lambda:not self.window.probers)
        master=self.root/'Master.json'
        master.write_text(json.dumps({'shot_count':2,'edit_duration_seconds':7,'records':[
            {'scene':'SC01','cut':'01-02','start_s':4,'end_s':7,'edit_duration_s':3},
            {'scene':'SC01','cut':'01-03','start_s':7,'end_s':11,'edit_duration_s':4}]}),encoding='utf-8')
        original_paths=[self.window.clip_table.item(row,2).text() for row in range(2)]
        original_output=self.window.output_edit.text()
        self.window.load_json(master)
        self.assertEqual([self.window.clip_table.item(row,4).text() for row in range(2)],['3','4'])
        self.assertEqual([self.window.clip_table.item(row,2).text() for row in range(2)],original_paths)
        self.assertEqual(self.window.output_edit.text(),original_output)
        self.assertIn('7s',self.window.state_label.text())
        master.write_text(json.dumps({'records':[{'scene':'SC01','cut':'01-02','start_s':4,'end_s':7,'edit_duration_s':3}]}),encoding='utf-8')
        with self.assertRaises(InputError):self.window.load_json(master)
        self.assertEqual([self.window.clip_table.item(row,4).text() for row in range(2)],['3','4'])

    def test_json_controls_motion_roundtrip_stale_denial(self):
        config=self.config();self.window.set_config(config);wait_until(lambda:not self.window.probers)
        self.window.clip_table.item(0,4).setText('1.5');self.window.clip_table.item(0,5).setText('0.4')
        self.window.boundary_table.item(0,2).setCheckState(Qt.Unchecked)
        self.window.clip_table.setCurrentCell(0,1);self.window.move_clip(1)
        self.assertEqual(self.window.build_config()['clips'][1]['id'],'shot0')
        saved=self.root/'saved.json';self.window.save_json(saved)
        roundtrip=load_job(saved);self.window.load_json(saved)
        self.assertEqual(self.window.build_config(),roundtrip)
        pause=self.root/'pause.mp4';make_positions_clip(pause,list(range(5,15))+[15]*10+list(range(15,35)))
        config=self.config_from_paths([pause,Path(config['clips'][1]['path'])])
        self.window.set_config(config)
        report=analyze_sources([probe(pause,'a'),probe(Path(config['clips'][1]['path']),'b')])
        reportpath=self.root/'motion.json';write_report(reportpath,report);self.window.load_motion_report(reportpath)
        self.assertGreater(self.window.motion_table.rowCount(),0)
        self.window.motion_table.item(0,0).setCheckState(Qt.Checked)
        self.window.motion_table.item(0,1).setCheckState(Qt.Checked)
        cfg=self.window.build_config();self.assertEqual(cfg['internal_motion']['selected_ids'],cfg['internal_motion']['excluded_ids'])
        motionjob=self.root/'motionjob.json';self.window.save_json(motionjob)
        self.window.load_json(motionjob);self.assertEqual(self.window.build_config(),load_job(motionjob))
        with pause.open('ab') as stream:stream.write(b'changed')
        before=self.window.revision
        with self.assertRaises(InputError):self.window.load_json(motionjob)
        self.window.output_edit.setText(str(self.root/'still-responsive'))
        self.assertGreater(self.window.revision,before)
        self.assertFalse(self.window._loading)

    def config_from_paths(self,paths):
        return normalize_job(dict(schema_version=1,output=dict(directory=str(self.root/'result'),fps=20),
            clips=[dict(id=f'shot{i}',path=str(p),target_seconds=2,protect_seconds=.3) for i,p in enumerate(paths)]),self.root)

    def test_real_async_job_playback_stale_and_screenshot(self):
        config=self.config();config['clips'][0]['target_seconds']=1.5;config['clips'][0]['protect_seconds']=.4
        self.window.set_config(config);wait_until(lambda:not self.window.probers)
        heartbeat=[];timer=QTimer();timer.timeout.connect(lambda:heartbeat.append(time.monotonic()));timer.start(10)
        outcomes=[];self.window.workerFinished.connect(outcomes.append)
        self.window.start_job();wait_until(lambda:bool(outcomes),60000);timer.stop()
        self.assertEqual(outcomes,['success'],self.window.log.toPlainText())
        self.assertGreater(len(heartbeat),10)
        output=Path(config['output']['directory'])
        executed=json.loads((output/'results/executed_job.json').read_text())
        self.assertEqual(executed['clips'][0]['target_seconds'],1.5)
        self.assertEqual(executed['clips'][0]['protect_seconds'],.4)
        self.assertEqual(executed['clips'][0]['max_speed'],9)
        self.assertEqual(executed['output']['fps'],20)
        viewer=self.window.viewer;self.assertGreater(viewer.frame_count,0)
        viewer.seek(2);QTest.mouseClick(viewer.next,Qt.LeftButton);self.assertEqual(viewer.position,3)
        QTest.mouseClick(viewer.previous,Qt.LeftButton);self.assertEqual(viewer.position,2)
        viewer.loop.setChecked(True);viewer.seek(viewer.frame_count-1);viewer.play();QTest.qWait(150)
        self.assertLess(viewer.position,viewer.frame_count-1);viewer.pause()
        report=json.loads((output/'results/report.json').read_text())
        self.assertAlmostEqual(report['timeline_validation']['measured_total_seconds'],3.5)
        self.assertEqual(self.window.timeline_table.rowCount(),2)
        screenshot=Path('outputs/ui-smoke.png');screenshot.parent.mkdir(exist_ok=True)
        self.window.grab().save(str(screenshot))
        self.window.clip_table.item(0,4).setText('1.6')
        self.assertIn('stale',self.window.state_label.text())

    def test_real_cancellation_keeps_unpublished_status(self):
        config=self.config(count=240);self.window.set_config(config);wait_until(lambda:not self.window.probers)
        outcomes=[];self.window.workerFinished.connect(outcomes.append);self.window.start_job()
        output=Path(config['output']['directory'])
        wait_until(lambda:self.window._worker_ready and output.exists(),30000)
        self.window.cancel_job();wait_until(lambda:bool(outcomes),30000)
        self.assertEqual(outcomes,['cancelled'],self.window.log.toPlainText())
        self.assertFalse((output/'results').exists())
        status=json.loads((output/'status.json').read_text());self.assertEqual(status['status'],'cancelled')


if __name__=='__main__':unittest.main()
