"""Read-only bounded-memory verification of the final real 11s/8s jobs."""
import hashlib,json,re,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'outputs/final-review-11s-8s'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rgb(path,filters='scale=320:180',w=320,h=180):
 p=subprocess.Popen(['ffmpeg','-v','error','-i',str(path),'-vf',filters,'-fps_mode','passthrough','-pix_fmt','rgb24','-f','rawvideo','-'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 try:
  while True:
   raw=p.stdout.read(w*h*3)
   if not raw:break
   assert len(raw)==w*h*3
   yield np.frombuffer(raw,np.uint8).reshape(h,w,3)
  assert p.wait()==0
 finally:
  if p.poll() is None:p.kill();p.wait()
  p.stdout.close()
def sample(path,index,w=1280,h=720):
 gen=rgb(path,f'select=eq(n\\,{index})',w,h)
 try:return next(gen)
 finally:gen.close()
# Immutable code state from D approval.
for path,expected in re.findall(r'\| `([^`]+)` \| `([a-f0-9]{64})` \|',(ROOT/'docs/reports/D_VERIFICATION.md').read_text()):
 if path.startswith('src/'):
  assert sha(ROOT/path)==expected,path
summary={};video_total=0
for name,targets in [('first-11s',[3,4,4]),('second-8s',[4,4])]:
 folder=BASE/name/'results';r=json.loads((folder/'report.json').read_text())
 assert r['settings']['targets']==targets
 assert r['settings']['protect']==[1]*len(targets)
 for c in r['clips']:assert sha(c['path'])==c['sha256']
 for video in folder.glob('*.mp4'):
  info=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(video)]))['streams']
  assert len(info)==1 and info[0]['codec_type']=='video'
  video_total+=1
  if video.name=='corrected.mp4':assert int(info[0]['nb_read_frames'])==sum(targets)*24
  for ci,target in enumerate(targets):
   if video.name in [f'clip_{ci+1:02d}.mp4',f'clip_{ci+1:02d}_diagnostic.mp4']:assert int(info[0]['nb_read_frames'])==target*24
 timeline=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(folder/'corrected.mp4')]))['frames']
 assert all(abs(float(f['best_effort_timestamp_time'])-i/24)<1e-6 for i,f in enumerate(timeline))
 maxerr=0;output=rgb(folder/'corrected.mp4');checked=0
 for ci,c in enumerate(r['clips']):
  rows=[row for row in r['corrected']['mapping'] if row['clip_id']==c['id']]
  ids=[row['source_frame'] for row in rows]
  assert ids==sorted(ids) and ids[0]==0 and ids[-1]==len(c['frames'])-1
  assert ids[:25]==list(range(25)) and len(ids)==targets[ci]*24
  source=rgb(c['path']);pos=-1;current=None
  try:
   for idx in ids:
    while pos<idx:current=next(source);pos+=1
    actual=next(output);error=float(np.abs(actual.astype(float)-current).mean())
    assert error<6,(name,ci,idx,error)
    maxerr=max(maxerr,error);checked+=1
  finally:source.close()
 output.close()
 assert not r['internal_motion']['selected'] and not r['internal_motion']['excluded']
 assert not any(d['applied'] for d in r['internal_motion']['decisions'])
 for comp in r['comparisons']:
  index=comp['boundary_frame_in_comparison'];row=comp['mapping'][index]
  picture=sample(folder/comp['video'],index,2560,744)
  assert row['relative_seconds']==0
  for side,prefix in enumerate(['baseline','corrected']):
   wanted=r[prefix]['boundaries'][comp['boundary']-1]['output_frame'];assert row[prefix]['output_frame']==wanted
   expected=sample(folder/f'{prefix}_diagnostic.mp4',wanted)
   assert np.abs(picture[80:,side*1280:(side+1)*1280].astype(float)-expected[56:]).mean()<5
 if name=='first-11s':
  d=r['decisions'][0];assert d['speed_applied'] and d['left_alpha']<0
  assert d['velocity_planning']['effective_before']>d['velocity_planning']['effective_after']
  assert d['side_results']['right']=='protected_interval_priority'
  assert not r['decisions'][1]['speed_applied']
  assert r['source_measurements'][1]['before']['confidence']<.35
 else:assert r['decisions'][0]['speed_reason']=='direction_conflict' and not r['decisions'][0]['speed_applied']
 summary[name]={'frames_compared':checked,'max_scaled_pixel_mae':maxerr,'report_sha256':sha(folder/'report.json'),'corrected_sha256':sha(folder/'corrected.mp4')}
report=json.loads((BASE/'internal-motion/results/motion_report.json').read_text())
assert len(report['sources'])==5 and sum(len(s['regions']) for s in report['sources'])==1
assert report['default_selected']==[]
for source in report['sources']:assert sha(source['path'])==source['sha256']
print(json.dumps({'status':'technical_pass_visual_quality_unapproved','video_count':video_total,'jobs':summary},indent=2))
