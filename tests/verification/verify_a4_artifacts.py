import json,hashlib,subprocess,sys
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'tests/verification'))
from test_a3_independent import frames
base=root/'outputs/a4-demo';manifest=json.loads((base/'manifest.json').read_text())
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
for seq in manifest['sequences'].values():
 for item in seq['inputs']:assert digest(item['path'])==item['sha256']
count=0
for run in manifest['runs']:
 assert digest(run['report'])==run['report_sha256']
 report=json.loads(Path(run['report']).read_text())
 for video in run['decoded_videos']:
  assert digest(video['path'])==video['sha256']
  info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames,duration,r_frame_rate','-of','json',video['path']]))['streams'][0]
  assert int(info['nb_read_frames'])==video['frames']
  assert abs(float(info['duration'])-video['duration_seconds'])<1e-5
  count+=1
 if run['name'].endswith('_off'):
  assert report['baseline']['mapping']==report['corrected']['mapping']
  assert np.array_equal(frames(Path(run['output'])/'results/baseline.mp4'),frames(Path(run['output'])/'results/corrected.mp4'))
 if run['name']=='stress_on':
  dec=report['decisions'];assert dec[0]['speed_applied'] and any(dec[0]['positional_schedule_changes'].values())
  assert dec[1]['speed_reason']=='direction_conflict' and not dec[1]['speed_applied']
  assert not dec[2]['speed_applied'] and not dec[2]['duplicate_removed']
  actual=frames(Path(run['output'])/'results/corrected.mp4')
  sources=[frames(item['path']) for item in manifest['sequences']['stress']['inputs']]
  for i,row in enumerate(report['corrected']['mapping']):
   source=sources[int(row['clip_id'].split('_')[1])-1][row['source_frame']]
   assert np.abs(actual[i].astype(float)-source).mean()<4
 if run['name']=='normal_clip2_disabled':
  assert all(not d['speed_applied'] and not d['duplicate_removed'] for d in report['decisions'][:2])
  rows=[r['source_frame'] for r in report['corrected']['mapping'] if r['clip_id']=='clip_02']
  assert rows==list(range(40))
assert count==65
print('Artifact audit PASS: 8 input hashes, 5 report hashes, 65 video hashes/counts/durations; off decoded equality; stress all-pixel source mapping; exclusions.')
print('manifest SHA256:',digest(base/'manifest.json'))
