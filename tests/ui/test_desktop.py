import json
import os
import shutil
from fractions import Fraction
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
from video_manager.job_schema import normalize_job,load_job,save_job
from video_manager.probe import probe
from video_manager.report import write_report
from video_manager.render import Encoder
from video_manager.ui.app import MainWindow
from unittest.mock import patch

APP=QApplication.instance() or QApplication([])


def wait_until(predicate,timeout=30000):
    end=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<end:QTest.qWait(20)
    if not predicate():raise AssertionError('Timed out waiting for UI condition')


class DesktopTests(unittest.TestCase):
    def test_completed_comparison_appears_and_plays_during_job(self):
        root=self.root/'live-job';work=root/'.work-test';work.mkdir(parents=True)
        video=work/'comparison_boundary_01.mp4'
        encoder=Encoder(video,64,48,Fraction(10))
        try:
            for shade in (40,60,80):encoder.write(bytes([shade,shade,shade])*64*48)
        finally:encoder.close()
        w=self.window;w._active_kind='render';w._active_output=root
        event=dict(stage='Creating comparison videos',done=1,total=2,completed_video=str(video))
        w._receive_progress(event);w._receive_progress(event)
        self.assertEqual(w.live_list.count(),1)
        self.assertIn('Final / Live previews (1)',w.tabs.tabText(w.tabs.indexOf(w.live_page)))
        w.live_list.setCurrentRow(0)
        wait_until(lambda:w.live_viewer.frame_count==3)
        self.assertTrue(w.live_viewer.timer.isActive())
        self.assertEqual(w.live_viewer.frame_count,3)
        self.assertTrue((Path(w._live_preview_copy.name)/video.name).is_file())
        shutil.copyfile(video,work/'comparison_boundary_02.mp4')
        work.rename(root/'results')
        w._relocate_live_previews()
        self.assertEqual(Path(w.live_list.item(0).data(Qt.UserRole)),root/'results'/video.name)
        w._receive_progress(dict(stage='Creating comparison videos',done=2,total=2,
                                 completed_video=str(work/'comparison_boundary_02.mp4')))
        self.assertEqual(w.live_list.count(),2)
        w.live_viewer.pause()
        w.live_viewer.seek(2)
        self.assertEqual(w.live_viewer.position,2)
        w._reset_live_previews()
        self.assertEqual(w.live_list.count(),0)
        self.assertEqual(w.live_viewer.frame_count,0)

    def test_live_preview_copy_keeps_ui_responsive(self):
        root=self.root/'live-slow';work=root/'.work-test';work.mkdir(parents=True)
        video=work/'comparison_boundary_01.mp4'
        encoder=Encoder(video,64,48,Fraction(10))
        try:
            for shade in (40,60,80):encoder.write(bytes([shade,shade,shade])*64*48)
        finally:encoder.close()
        w=self.window;w._active_kind='render';w._active_output=root
        w._receive_progress(dict(stage='Creating comparison videos',done=1,total=1,completed_video=str(video)))
        ticks=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1))
        original=shutil.copyfile
        def slow_copy(source,destination):
            time.sleep(.3)
            return original(source,destination)
        with patch('video_manager.ui.app.shutil.copyfile',side_effect=slow_copy):
            timer.start();w.live_list.setCurrentRow(0)
            QTest.qWait(100)
            self.assertGreater(len(ticks),0)
            wait_until(lambda:w.live_viewer.frame_count==3)
        timer.stop()

    def test_enhancement_html_help_opens_local_packaged_file(self):
        w=self.window;revision=w.revision
        with patch('video_manager.ui.app.QDesktopServices.openUrl',return_value=True) as opened:
            w.enhancement_help_button.click()
        opened.assert_called_once()
        url=opened.call_args.args[0]
        self.assertTrue(url.isLocalFile())
        path=Path(url.toLocalFile())
        self.assertEqual(path.name,'video_enhancements_help.html')
        html=path.read_text(encoding='utf-8')
        self.assertIn('Maximum crop',html)
        self.assertIn('프레임 보간',html)
        self.assertEqual(w.revision,revision)

    def test_enhancement_controls_roundtrip_and_stale(self):
        config=self.config();self.window.set_config(config)
        wait_until(lambda:not self.window.probers)
        w=self.window
        self.assertFalse(w.interpolate_check.isChecked());self.assertFalse(w.stabilize_check.isChecked())
        w.result_revision=w.revision
        w.interpolate_check.setChecked(True);w.stabilize_check.setChecked(True)
        w.crop_percent.setValue(4);w.stabilize_strength.setValue(.8)
        self.assertGreater(w.revision,w.result_revision)
        saved=w.build_config();path=self.root/'enhanced.json';w.save_json(path)
        self.assertEqual(load_job(path),saved)
        w.interpolate_check.setChecked(False);w.load_json(path)
        self.assertTrue(w.interpolate_check.isChecked());self.assertTrue(w.stabilize_check.isChecked())
        self.assertEqual(w.build_config()['enhancements'],saved['enhancements'])

    def test_progress_estimate_stage_reset_and_completion_time(self):
        w=self.window
        w._started_at=100;w._stage='Preparing';w._stage_done=0
        with patch('video_manager.ui.app.time.monotonic',return_value=110):
            w._receive_progress(dict(stage='Render',done=0,total=100))
            self.assertIn('Calculating',w.time_label.text())
        with patch('video_manager.ui.app.time.monotonic',return_value=120):
            w._receive_progress(dict(stage='Render',done=25,total=100))
            self.assertIn('Elapsed: 00:00:20',w.time_label.text())
            self.assertIn('~00:00:30',w.time_label.text())
            self.assertEqual(w.progress.value(),250)
            w._receive_progress(dict(stage='Finalizing',done=0,total=0))
            self.assertIn('Calculating',w.time_label.text())
            self.assertEqual(w.progress.maximum(),0)
            w._cancel_requested=True
            w._finished(1,QProcess.NormalExit)
            self.assertFalse(w.work_timer.isActive())
            self.assertEqual(w.time_label.text(),'cancelled · Elapsed: 00:00:20')

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

    def test_narration_files_roundtrip_through_job_json(self):
        w=self.window;config=self.config(count=80)
        self.assertEqual(set(w.narration_fields),{'audio_path','subtitle_srt','shot_mapping_csv'})
        self.assertIn('Spanish_Armada_Subtitles_120s_Resolve.srt',w.narration_guide.toPlainText())
        self.assertIn('TTS_Subtitle_30Shot_Mapping.csv',w.narration_guide.toPlainText())
        self.assertNotIn('Subtitle_Timing_Detail.csv',w.narration_guide.toPlainText())
        audio=self.root/'narration.mp3';audio.write_bytes(b'audio placeholder')
        subtitles=self.root/'subtitles.srt';subtitles.write_text('subtitle placeholder',encoding='utf-8')
        config['narration']['audio_path']=str(audio)
        config['narration']['subtitle_srt']=str(subtitles)
        w.set_config(config)
        self.assertEqual(w.narration_fields['audio_path'].text(),str(audio))
        self.assertIn('2 of 3 files selected',w.narration_summary.text())
        job=self.root/'saved.json';w.save_json(job)
        w.set_config(load_job(job))
        self.assertEqual(w.narration_fields['audio_path'].text(),str(audio))
        self.assertEqual(w.build_config()['narration']['subtitle_srt'],str(subtitles))

    def test_subtitle_style_controls_roundtrip(self):
        w=self.window;w.set_config(self.config(count=80))
        font_path=self.root/'custom.ttf';font_path.write_bytes(b'font fixture')
        w.subtitle_font_file.setText(str(font_path))
        w.subtitle_preset.setCurrentIndex(w.subtitle_preset.findData('black_strong'))
        self.assertTrue(w.subtitle_background.isChecked())
        self.assertEqual(w.subtitle_background_opacity.value(),78)
        w.subtitle_size.setValue(34)
        w.subtitle_position.setValue(18)
        w.subtitle_alignment.setCurrentIndex(w.subtitle_alignment.findData('left'))
        w.subtitle_margin.setValue(48)
        w.subtitle_background.setChecked(True)
        w.subtitle_background_opacity.setValue(67)
        w.subtitle_outline.setChecked(False)
        w._set_subtitle_color('#FFFF00')
        style=w.build_config()['narration']['subtitle_style']
        job=self.root/'subtitle_style.json';w.save_json(job)
        w.set_config(load_job(job))
        self.assertEqual(w.build_config()['narration']['subtitle_style'],style)

    def test_final_video_is_added_and_opened_in_live_tab(self):
        result=self.root/'completed';results=result/'results';results.mkdir(parents=True)
        video=results/'corrected.mp4';encoder=Encoder(video,64,48,Fraction(10))
        try:
            for shade in (40,60,80):encoder.write(bytes([shade,shade,shade])*64*48)
        finally:encoder.close()
        w=self.window;w.result_dir=result
        w._add_final_video_preview(play=True)
        self.assertEqual(w.live_list.currentItem().text(),'Final video · click to play')
        self.assertEqual(w.tabs.currentWidget(),w.live_page)
        self.assertEqual(w.live_viewer.frame_count,3)
        self.assertTrue(w.live_viewer.timer.isActive())

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
        self.assertIn(str(master.resolve()),self.window.json_label.text())
        self.assertIn('full plan: 2 clips / 7s',self.window.json_label.text())
        self.assertEqual(json.loads(self.window.json_preview.toPlainText())['shot_count'],2)
        self.assertEqual([float(self.window.clip_table.item(row,8).text()) for row in range(2)],[3,4])
        self.window.clip_table.item(0,4).setText('2')
        self.assertIn('total 6s',self.window.timing_summary.text())
        self.assertIn('1 targets changed',self.window.timing_summary.text())
        self.assertEqual(float(self.window.clip_table.item(0,8).text()),3)
        self.window.clip_table.item(0,4).setText('3')
        master.write_text(json.dumps({'records':[{'scene':'SC01','cut':'01-02','start_s':4,'end_s':7,'edit_duration_s':3}]}),encoding='utf-8')
        with self.assertRaises(InputError):self.window.load_json(master)
        self.assertEqual([self.window.clip_table.item(row,4).text() for row in range(2)],['3','4'])

    def test_clips_added_after_master_keep_master_targets_after_probe(self):
        first=make_motion_clip(self.root/'03-03.mp4',5,35,count=100)
        later=make_motion_clip(self.root/'05-01.mp4',10,40,count=100)
        self.window.add_clip(first);wait_until(lambda:not self.window.probers)
        master=self.root/'Master.json'
        master.write_text(json.dumps({'shot_count':2,'edit_duration_seconds':9,'records':[
            {'scene':'SC03','cut':'03-03','start_s':43,'end_s':48,'edit_duration_s':5},
            {'scene':'SC05','cut':'05-01','start_s':76,'end_s':80,'edit_duration_s':4}]}),encoding='utf-8')
        self.window.load_json(master)
        self.window.add_clip(later);wait_until(lambda:not self.window.probers)
        self.assertEqual([self.window.clip_table.item(row,4).text() for row in range(2)],['5','4'])
        self.assertEqual([self.window.clip_table.item(row,8).text() for row in range(2)],['5.0','4.0'])
        self.assertIn('imported 2 clips',self.window.json_label.text())
        self.assertEqual([clip['target_seconds'] for clip in self.window.build_config()['clips']],[5,4])
        with self.assertRaisesRegex(InputError,'No Master timing'):
            self.window.add_clip(self.root/'07-01.mp4')
        self.assertEqual(self.window.clip_table.rowCount(),2)

    def test_ten_second_targets_are_red_and_disabled_after_load_or_add(self):
        source=make_motion_clip(self.root/'03-03.mp4',5,35,count=40)
        other=make_motion_clip(self.root/'03-04.mp4',10,40,count=40)
        job=self.root/'old-job.json'
        job.write_text(json.dumps({'schema_version':1,'output':{'directory':str(self.root/'result')},
            'clips':[{'id':'clip_01','path':str(source),'target_seconds':10},
                     {'id':'clip_02','path':str(other),'target_seconds':2}]}),encoding='utf-8')
        self.window.load_json(job);wait_until(lambda:not self.window.probers)
        table=self.window.clip_table
        self.assertEqual(table.item(0,0).checkState(),Qt.Unchecked)
        self.assertEqual(table.item(0,4).background().color().name(),'#ffe1e1')
        self.assertIn('1 10s targets need review',self.window.timing_summary.text())
        self.assertFalse(self.window.build_config()['clips'][0]['correction_enabled'])

        table.item(0,4).setText('5')
        self.assertEqual(table.item(0,4).background().style(),Qt.NoBrush)
        self.assertEqual(table.item(0,0).checkState(),Qt.Unchecked)
        table.item(0,0).setCheckState(Qt.Checked)
        self.assertTrue(self.window.build_config()['clips'][0]['correction_enabled'])

        added=self.root/'05-01.mp4'
        with patch.object(self.window,'request_probe'):
            self.window.add_clip(added)
        self.window._probed(str(added.resolve()),{'duration':10})
        self.assertEqual(table.item(2,4).text(),'10.000000')
        self.assertEqual(table.item(2,0).checkState(),Qt.Unchecked)
        self.assertEqual(table.item(2,4).background().color().name(),'#ffe1e1')

    def test_load_button_deletes_saved_job_until_save_button_recreates_it(self):
        config=self.config();job=self.root/'saved.json';save_job(config,job)
        with patch('video_manager.ui.app.QFileDialog.getOpenFileName',return_value=(str(job),'JSON (*.json)')):
            self.window.choose_load()
        wait_until(lambda:not self.window.probers)
        self.assertFalse(job.exists())
        self.assertEqual(self.window._pending_save_path,job.resolve())
        self.assertIn('Save JSON to recreate it',self.window.json_label.text())

        self.window.clip_table.item(0,4).setText('1.5')
        with patch('video_manager.ui.app.QFileDialog.getSaveFileName',return_value=(str(job),'JSON (*.json)')) as dialog:
            self.window.choose_save()
        self.assertEqual(dialog.call_args.args[2],str(job))
        self.assertTrue(job.is_file())
        self.assertEqual(load_job(job)['clips'][0]['target_seconds'],1.5)
        self.assertIsNone(self.window._pending_save_path)

    def test_load_button_keeps_master_reference_file(self):
        paths=[make_motion_clip(self.root/name,5+i*30,35+i*30,count=40)
               for i,name in enumerate(['03-03.mp4','03-04.mp4'])]
        for path in paths:self.window.add_clip(path)
        wait_until(lambda:not self.window.probers)
        master=self.root/'Master.json'
        master.write_text(json.dumps({'shot_count':2,'edit_duration_seconds':8,'records':[
            {'scene':'SC03','cut':'03-03','start_s':43,'end_s':48,'edit_duration_s':5},
            {'scene':'SC03','cut':'03-04','start_s':48,'end_s':51,'edit_duration_s':3}]}),encoding='utf-8')
        with patch('video_manager.ui.app.QFileDialog.getOpenFileName',return_value=(str(master),'JSON (*.json)')):
            self.window.choose_load()
        self.assertTrue(master.is_file())
        self.assertIsNone(self.window._pending_save_path)
        self.assertEqual([self.window.clip_table.item(row,4).text() for row in range(2)],['5','3'])

    def test_load_button_preserves_job_file_if_loading_fails(self):
        invalid=self.root/'invalid.json';invalid.write_text('{broken',encoding='utf-8')
        with patch('video_manager.ui.app.QFileDialog.getOpenFileName',return_value=(str(invalid),'JSON (*.json)')):
            with self.assertRaises(InputError):self.window.choose_load()
        self.assertTrue(invalid.is_file())
        self.assertIsNone(self.window._pending_save_path)

    def test_json_controls_motion_roundtrip_stale_denial(self):
        config=self.config();self.window.set_config(config);wait_until(lambda:not self.window.probers)
        self.window.clip_table.item(0,4).setText('1.5');self.window.clip_table.item(0,5).setText('0.4')
        self.window.boundary_table.item(0,2).setCheckState(Qt.Unchecked)
        self.window.clip_table.setCurrentCell(0,1);self.window.move_clip(1)
        self.assertEqual(self.window.build_config()['clips'][1]['id'],'shot0')
        saved=self.root/'saved.json';self.window.save_json(saved)
        roundtrip=load_job(saved);self.window.load_json(saved)
        self.assertEqual(self.window.build_config(),roundtrip)
        self.assertIn(str(saved.resolve()),self.window.json_label.text())
        self.assertEqual([float(self.window.clip_table.item(row,8).text()) for row in range(2)],
                         [c['target_seconds'] for c in roundtrip['clips']])
        self.assertEqual(json.loads(self.window.json_preview.toPlainText()),json.loads(saved.read_text(encoding='utf-8')))
        pause=self.root/'pause.mp4';make_positions_clip(pause,list(range(5,15))+[15]*10+list(range(15,35)))
        config=self.config_from_paths([pause,Path(config['clips'][1]['path'])])
        self.window.set_config(config)
        report=analyze_sources([probe(pause,'a'),probe(Path(config['clips'][1]['path']),'b')])
        reportpath=self.root/'motion.json';write_report(reportpath,report);self.window.load_motion_report(reportpath)
        self.assertGreater(self.window.motion_table.rowCount(),0)
        self.assertIn('motion-v2',self.window.motion_summary.text())
        self.assertIn('%',self.window.motion_table.item(0,6).text())
        self.assertIn('review',self.window.motion_table.item(0,7).text())
        self.assertFalse(self.window.motion_table.item(0,0).flags() & Qt.ItemIsUserCheckable)
        self.window.clear_motion()
        # Legacy selections remain reproducible; v2 holds are diagnostic-only.
        report=analyze_sources([probe(pause,'a'),probe(Path(config['clips'][1]['path']),'b')],version='motion-v1')
        reportpath=self.root/'legacy-motion.json';write_report(reportpath,report);self.window.load_motion_report(reportpath)
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
