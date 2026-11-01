import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from video_manager.errors import InputError
from video_manager.narration import (validate_narration,render_narration,normalize_subtitle_style,
                                     subtitle_filter,write_positioned_ass)


class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.assets={key:str(self.root/name) for key,name in
            [('audio_path','voice.mp3'),('subtitle_srt','words.srt'),('shot_mapping_csv','shots.csv')]}
        Path(self.assets['audio_path']).write_bytes(b'test audio placeholder')
        Path(self.assets['subtitle_srt']).write_text('1\n00:00:00,000 --> 00:00:02,000\nHello\n\n2\n00:00:02,000 --> 00:00:04,000\nWorld\n',encoding='utf-8')
        self.clips=[dict(id=str(i),path=f'01-0{i}.mp4',target_seconds=2) for i in (1,2)]
        with Path(self.assets['shot_mapping_csv']).open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(['shot','video_in_s','video_out_s','duration_s','subtitle_numbers'])
            writer.writerows([['01-01',0,2,2,'1'],['01-02',2,4,2,'2']])

    def tearDown(self):self.temp.cleanup()

    def tool(self,args,**kwargs):
        if args[0]=='ffprobe':
            if 'stream=width,height' in args:
                return SimpleNamespace(stdout=json.dumps({'streams':[{'width':640,'height':360}]}))
            return SimpleNamespace(stdout=json.dumps({'streams':[{'duration':'4.2'}]}))
        return SimpleNamespace(stdout=' ... subtitles V->V Render text subtitles')

    def test_valid_plan_and_partial_selection(self):
        with patch('video_manager.narration.run_tool',side_effect=self.tool):
            plan=validate_narration(self.assets,self.clips)
        self.assertAlmostEqual(plan['tempo'],1.05)
        self.assertEqual(plan['subtitle_count'],2)
        with self.assertRaises(InputError):validate_narration({'audio_path':self.assets['audio_path']},self.clips)

    def test_reject_mismatched_shot_order_target_and_subtitles(self):
        with self.assertRaises(InputError):validate_narration(self.assets,self.clips[::-1],probe_audio=False)
        self.clips[0]['target_seconds']=3
        with self.assertRaises(InputError):validate_narration(self.assets,self.clips,probe_audio=False)
        self.clips[0]['target_seconds']=2
        path=Path(self.assets['shot_mapping_csv']);path.write_text(path.read_text().replace('01-02,2,4,2,2','01-02,2,4,2,1'))
        with self.assertRaises(InputError):validate_narration(self.assets,self.clips,probe_audio=False)

    def test_render_command_without_running_ffmpeg(self):
        with patch('video_manager.narration.run_tool',side_effect=self.tool):
            plan=validate_narration(self.assets,self.clips)
        work=self.root/'work';work.mkdir();(work/'corrected.mp4').write_bytes(b'original')
        def fake_render(args,**kwargs):
            if args[0]=='ffprobe':
                return SimpleNamespace(stdout=json.dumps({'streams':[{'width':640,'height':360}]}))
            self.assertEqual(kwargs['cwd'],str(work))
            graph=args[args.index('-filter_complex')+1]
            self.assertIn('atempo=1.05',graph)
            self.assertIn('volume=0.35',graph)
            self.assertIn('subtitles=narration.ass',graph)
            Path(args[-1]).write_bytes(b'mocked output')
        with patch('video_manager.narration.run_tool',side_effect=fake_render):
            details=render_narration(work,plan,has_background=True)
        self.assertEqual((work/'corrected.mp4').read_bytes(),b'mocked output')
        self.assertEqual(details['subtitles'],'burned_in')
        Path(self.assets['audio_path']).write_bytes(b'changed')
        with self.assertRaises(InputError):render_narration(work,plan,has_background=False)

    def test_subtitle_style_validation_and_render_filter(self):
        style=normalize_subtitle_style(dict(font='Arial',size=32,position='top',margin=40,background=True))
        graph=subtitle_filter(style)
        self.assertIn('FontName=Arial',graph)
        self.assertIn('FontSize=32',graph)
        self.assertIn('Alignment=8',graph)
        self.assertIn('BorderStyle=3',graph)
        self.assertEqual(normalize_subtitle_style(dict(position='top'))['vertical_position'],12)
        for bad in (dict(font="Arial',Outline=0"),dict(size=0),dict(position='left'),dict(background='yes')):
            with self.assertRaises(InputError):normalize_subtitle_style(bad)

    def test_positioned_ass_uses_slider_coordinate(self):
        target=self.root/'positioned.ass'
        write_positioned_ass(self.assets['subtitle_srt'],target,
            normalize_subtitle_style(dict(vertical_position=88,alignment='center')),640,360)
        rendered=target.read_text(encoding='utf-8')
        self.assertIn('PlayResX: 640',rendered)
        self.assertIn(r'{\pos(320,317)}',rendered)

    def test_job_style_round_trip(self):
        from video_manager.job_schema import normalize_job,save_job,load_job
        data=dict(schema_version=1,output=dict(directory=str(self.root/'output')),
                  clips=self.clips,narration={**self.assets,'subtitle_style':dict(
                      font='Arial',size=31,position='middle',margin=12,background=True)})
        config=normalize_job(data,self.root)
        path=self.root/'job.json'
        save_job(config,path)
        self.assertEqual(load_job(path)['narration']['subtitle_style'],config['narration']['subtitle_style'])

    def test_job_forwards_narration_without_rendering(self):
        from video_manager.job_schema import normalize_job,run_job
        config=normalize_job(dict(schema_version=1,output=dict(directory=str(self.root/'output')),
            clips=self.clips,narration=self.assets),self.root)
        with patch('video_manager.job_schema.validate_job',return_value=(config,{'config_sha256':'test'})), \
             patch('video_manager.job_schema.retime',return_value='mocked') as renderer:
            self.assertEqual(run_job(config),'mocked')
        self.assertEqual(renderer.call_args.kwargs['narration'],config['narration'])
