"""CPU motion evidence, in source time. Classification is never proof of intent.

Pyramidal LK separates a spatially supported camera model from local residuals.
Unreliable transitions are barriers: temporal candidates never cross them.
"""
from collections import Counter

import cv2
import numpy as np

ANALYSIS_VERSION = 'motion-components-v2.4'


def analysis_size(width, height, max_side=480, sample_aspect_ratio=1):
    width = float(width)*float(sample_aspect_ratio)
    factor = min(1., max_side/max(width, height))
    return max(1, round(width*factor)), max(1, round(height*factor))


def _gray(frame):
    frame = np.asarray(frame)
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY) if frame.ndim == 3 else frame.astype(np.uint8)


def _pair(previous, current, dt):
    height, width = current.shape
    difference = current.astype(float)-previous.astype(float)
    mae = float(np.mean(np.abs(difference)))
    brightness = float(np.median(difference))
    centered_mae = float(np.mean(np.abs(difference-brightness)))
    correlation=float(np.corrcoef(previous.ravel()[::8],current.ravel()[::8])[0,1]) if np.std(previous)>1 and np.std(current)>1 else 0.
    result = dict(dt=float(dt), mae=mae, speed=0., camera_speed=0., object_speed=0.,
                  camera_dx=0., camera_dy=0., camera_rotation=0., camera_confidence=0.,
                  confidence=0., abstain_reason='', cut=False,
                  illumination_change=abs(brightness)>5, track_count=0, regions=[])
    # A flash/exposure change is not a camera movement or a scene cut.
    if mae>20 and correlation<.3:
        result.update(cut=True,abstain_reason='scene_cut')
        return result
    if abs(brightness)>2 and correlation>.9 and centered_mae < max(8., abs(brightness)*.65):
        result['abstain_reason']='illumination_change'
        result['illumination_change']=True
        return result
    # Spatial quotas keep a bright subject from starving the background of tracks.
    groups=[]
    for row in range(3):
        for col in range(3):
            x0,x1=col*width//3,(col+1)*width//3
            y0,y1=row*height//3,(row+1)*height//3
            points=cv2.goodFeaturesToTrack(previous[y0:y1,x0:x1],45,.02,5,blockSize=5)
            if points is not None:
                points+=np.array([x0,y0],dtype=np.float32)
                groups.append(points)
    points=np.concatenate(groups) if groups else None
    if points is None or len(points)<8:
        result['abstain_reason']='low_texture'
        result['cut']=centered_mae>35
        return result
    nxt,status,_=cv2.calcOpticalFlowPyrLK(previous,current,points,None,winSize=(21,21),maxLevel=3)
    back,back_status,_=cv2.calcOpticalFlowPyrLK(current,previous,nxt,None,winSize=(21,21),maxLevel=3)
    good=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<1.)
    p=points.reshape(-1,2)[good]; q=nxt.reshape(-1,2)[good]
    good_fraction=len(p)/len(points)
    result['track_count']=len(p)
    if centered_mae>35 and good_fraction<.6:
        result.update(cut=True,abstain_reason='scene_cut')
        return result
    if len(p)<8 or good_fraction<.55:
        result['abstain_reason']='tracking_loss_or_occlusion'
        return result
    vectors=q-p
    cells=np.minimum(2,(p/np.array([width,height])*3).astype(int))
    matrix,inliers=cv2.estimateAffinePartial2D(p,q,method=cv2.RANSAC,ransacReprojThreshold=.8,
                                              maxIters=1000,confidence=.99,refineIters=10)
    camera=np.zeros_like(vectors)
    if matrix is not None:
        mask=inliers.ravel().astype(bool)
        covered=len(set(map(tuple,cells[mask])))
        # A single textured subject cannot establish a camera model.
        if covered>=5 and np.mean(mask)>=.5:
            camera=p@matrix[:,:2].T+matrix[:,2]-p
            center=np.array([width/2,height/2])
            displacement=matrix[:,:2]@center+matrix[:,2]-center
            result.update(camera_dx=float(displacement[0]),camera_dy=float(displacement[1]),
                          camera_rotation=float(np.arctan2(matrix[1,0],matrix[0,0])),
                          camera_speed=float(np.linalg.norm(displacement))/dt,
                          camera_confidence=float(np.mean(mask)*good_fraction))
    residual=vectors-camera
    magnitude=np.linalg.norm(residual,axis=1)
    active=magnitude>.25
    # Keep separate spatial motion evidence; opposite objects must not cancel.
    local=[]
    for cell in sorted(set(map(tuple,cells[active]))):
        mask=active & np.all(cells==cell,axis=1)
        if np.count_nonzero(mask)<3:
            continue
        vector=np.median(residual[mask],axis=0)
        local.append(dict(cell=[int(v) for v in cell],dx=float(vector[0]),dy=float(vector[1]),
                          speed=float(np.linalg.norm(vector))/dt,count=int(np.count_nonzero(mask))))
    result['regions']=local
    if local:
        result['object_speed']=float(np.median(magnitude[active]))/dt
    result['speed']=result['object_speed']
    result['confidence']=float(min(1.,good_fraction)*min(1.,len(p)/20))
    if any(a['dx']*b['dx']+a['dy']*b['dy'] < -.15
           for i,a in enumerate(local) for b in local[i+1:]):
        result.update(abstain_reason='conflicting_object_motion',confidence=0.)
    # Tracks concentrated in the subject are useful evidence but no camera proof.
    if result['camera_confidence']==0:
        result['camera_model_reason']='insufficient_background_support'
    return result


def analyze_frames(frames, times, options=None):
    """Analyze an iterable of RGB/gray frames without retaining the video in RAM."""
    options=options or {}
    window=float(options.get('window_seconds',.4))
    freeze=float(options.get('freeze_seconds',.2))
    ratio=float(options.get('change_ratio',2.5))
    times=np.asarray(times,dtype=float)
    if len(times)<1 or not np.all(np.isfinite(times)) or np.any(np.diff(times)<=0):
        raise ValueError('Motion timestamps must be finite and strictly increasing')
    pairs=[]; previous=None; count=0; size=None
    for index,frame in enumerate(frames):
        if index>=len(times):
            raise ValueError('More decoded frames than source timestamps')
        gray=_gray(frame)
        if size is None: size=(gray.shape[1],gray.shape[0])
        if gray.shape!=(size[1],size[0]): raise ValueError('Frame dimensions changed')
        if previous is not None:
            pair=_pair(previous,gray,float(times[index]-times[index-1]))
            pair.update(frame=index,seconds=float(times[index]))
            pairs.append(pair)
        previous=gray; count+=1
    if count!=len(times): raise ValueError('Decoded frame count differs from timestamps')
    regions=[]
    def add(start,end,kind,evidence):
        start=max(float(times[0]),float(start)); end=min(float(times[-1]),float(end))
        inside=[p for p in pairs if start<p['seconds']<=end]
        if not inside or any(p['abstain_reason'] for p in inside): return
        regions.append(dict(start_seconds=start,end_seconds=end,kinds=[kind],evidence=[evidence]))
    start=None; held_runs=[]
    for index in range(len(pairs)+1):
        held=False
        if index<len(pairs):
            pair=pairs[index]
            camera_displacement=np.hypot(pair['camera_dx'],pair['camera_dy'])+abs(pair['camera_rotation'])*np.hypot(*size)/2
            # A small moving subject can contribute <.5 whole-frame MAE. Its
            # tracked movement overrides that misleading frame-average signal.
            held=(pair['mae']<.5 and pair['object_speed']*pair['dt']<.1 and
                  camera_displacement<.1 and not pair['abstain_reason'])
        if held and start is None: start=index
        if not held and start is not None:
            elapsed=sum(p['dt'] for p in pairs[start:index])
            held_runs.append((start,index,float(elapsed)))
            start=None
    # Slow subpixel motion naturally repeats decoded frames at a regular cadence.
    # Estimate that cadence from this clip's repeated runs before expanding windows:
    # otherwise overlapping windows can absorb a distant genuine speed jump and
    # incorrectly make the entire candidate intersect the protected opening.
    cadence=float(np.median([run[2] for run in held_runs])) if len(held_runs)>=3 else 0.
    minimum_hold=max(freeze,2*cadence+float(np.median(np.diff(times)))) if cadence else freeze
    hold_cores=[]
    for first,last,elapsed in held_runs:
        if elapsed>=minimum_hold-1e-9:
            core_start=float(times[pairs[first]['frame']-1]); core_end=float(times[pairs[last-1]['frame']])
            hold_cores.append((core_start,core_end))
            add(times[pairs[first]['frame']-1]-window,times[pairs[last-1]['frame']]+window,
                'repeat_or_hold',dict(held_seconds=elapsed,held_start_seconds=core_start,held_end_seconds=core_end,
                                     regular_repeat_cadence_seconds=cadence,intent='unknown'))
    for split in np.arange(times[0]+window,times[-1]-window,window/2):
        left=[p for p in pairs if split-window<p['seconds']<=split]
        right=[p for p in pairs if split<p['seconds']<=split+window]
        if not left or not right: continue
        a=float(np.mean([p['speed'] for p in left])); b=float(np.mean([p['speed'] for p in right]))
        if min(a,b)>.5 and max(a,b)/(min(a,b)+.1)>=ratio:
            add(split-window,split+window,'speed_change',dict(before_speed=a,after_speed=b,intent='unknown'))
    grouped={}
    for region in sorted(regions,key=lambda r:r['start_seconds']):
        # Diagnostic holds and correctable speed hints have different policies.
        # Never union their bounds: a protected/ambiguous hold must not swallow
        # a later independently observed speed transition.
        merged=grouped.setdefault(tuple(region['kinds']),[])
        if merged and region['start_seconds']<=merged[-1]['end_seconds']:
            previous_region=merged[-1]
            previous_region['end_seconds']=max(previous_region['end_seconds'],region['end_seconds'])
            previous_region['kinds']=sorted(set(previous_region['kinds']+region['kinds']))
            previous_region['evidence']+=region['evidence']
        else: merged.append(region)
    merged=sorted((region for group in grouped.values() for region in group),key=lambda r:r['start_seconds'])
    for region in merged:
        start,end=region['start_seconds'],region['end_seconds']
        samples=[p for p in pairs if start<p['seconds']<=end]
        region.update(first_frame=int(np.argmin(abs(times-start))),last_frame=int(np.argmin(abs(times-end))),
            fully_static=all(p['mae']<.5 for p in samples),proposal_kind='optimized',proposal_amount=0.,
            confidence=float(min(p['confidence'] for p in samples)),
            review_reason='requires_visual_review_intent_unknown',interpretation='suspicion_only_not_a_defect',
            motion_samples=[{key:p[key] for key in ('seconds','speed','confidence','dt')} for p in samples],
            context_motion_samples=[{key:p[key] for key in ('seconds','speed','confidence','dt')} for p in pairs],
            source_frame_times=times.tolist())
        # Only actual hold frames are an intent barrier, not the padded review
        # window. An independent later jump can still get a separate candidate.
        region['ambiguous_hold_overlap']=any(start<right and end>left for left,right in hold_cores)
    return dict(analysis_version=ANALYSIS_VERSION,pairs=pairs,regions=merged,
        diagnostics=dict(analysis_size=list(size),aspect_preserved=True,
            method='pyramidal_LK_forward_backward_RANSAC_affine_residual_cells',
            cuts=[p['seconds'] for p in pairs if p['cut']],
            abstentions=dict(Counter(p['abstain_reason'] for p in pairs if p['abstain_reason'])),
            automatic_application=False,limitations='No semantic intent inference, deformation repair, stabilization or interpolation'))


def analyze_motion(clip, options=None):
    from .render import decode_frames
    from .progress import report
    width,height=analysis_size(clip.width,clip.height,sample_aspect_ratio=clip.sample_aspect_ratio)
    def frames():
        for index,raw in enumerate(decode_frames(clip,width,height)):
            report(f'Analyze motion · {clip.id}',index+1,len(clip.frames))
            yield np.frombuffer(raw,np.uint8).reshape(height,width,3)
    return analyze_frames(frames(),[f['source_seconds'] for f in clip.frames],options)
