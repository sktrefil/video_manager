"""Review-only motion suspicions, source-bound IDs, and explicit local candidates."""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .errors import InputError
from .probe import probe
from .render import decode_frames, render_clips
from .report import file_hash, write_report
from .time_map import TimeMap, number, select_schedule

VERSION='motion-v1'
DEFAULT_OPTIONS={'freeze_seconds':0.2,'change_ratio':2.5,'window_seconds':0.4}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def normalize_options(options=None):
    options=DEFAULT_OPTIONS if options is None else options
    if not isinstance(options,dict) or set(options)!=set(DEFAULT_OPTIONS):
        raise InputError('Unknown or missing motion-analysis options')
    result={key:number(value,key,positive=True) for key,value in options.items()}
    if result['change_ratio']<=1 or result['window_seconds']>2 or result['freeze_seconds']>10:
        raise InputError('Motion options require change_ratio > 1, window <= 2s, freeze <= 10s')
    return result


def region_id(source_hash,options,region):
    body={k:v for k,v in region.items() if k!='id'}
    return 'region_'+digest({'version':VERSION,'source_sha256':source_hash,'options':options,'region':body})[:20]


def analyze_clip(clip,options):
    previous=None
    pairs=[]
    for i,raw in enumerate(decode_frames(clip,160,96)):
        gray=cv2.cvtColor(np.frombuffer(raw,np.uint8).reshape(96,160,3),cv2.COLOR_RGB2GRAY)
        if previous is not None:
            dt=clip.frames[i]['source_seconds']-clip.frames[i-1]['source_seconds']
            flow=cv2.calcOpticalFlowFarneback(previous,gray,None,.5,3,15,3,5,1.2,0)
            magnitude=np.linalg.norm(flow,axis=2)
            active=magnitude>.1
            speed=float(np.median(magnitude[active]))/dt if np.any(active) else 0.0
            mae=float(np.mean(np.abs(gray.astype(float)-previous)))
            pairs.append({'frame':i,'seconds':clip.frames[i]['source_seconds'],'dt':dt,'speed':speed,'mae':mae})
        previous=gray
    times=[f['source_seconds'] for f in clip.frames]
    raw_regions=[]
    run_start=None
    for index in range(len(pairs)+1):
        frozen=index<len(pairs) and pairs[index]['mae']<.5
        if frozen and run_start is None:
            run_start=index
        if not frozen and run_start is not None:
            duration=sum(p['dt'] for p in pairs[run_start:index])
            if duration>=options['freeze_seconds']-1e-9:
                first=pairs[run_start]['frame']-1
                last=pairs[index-1]['frame']
                start=max(0,times[first]-options['window_seconds'])
                end=min(times[-1],times[last]+options['window_seconds'])
                raw_regions.append({'start_seconds':start,'end_seconds':end,'kinds':['repeat_or_hold'],
                                    'evidence':[{'held_seconds':duration,'first_frame':first,'last_frame':last}]})
            run_start=None
    window=options['window_seconds']
    # Aggregate full windows so a normal low-speed one-frame repeat is not a speed spike.
    for split in np.arange(window,times[-1]-window,window/2):
        before=[p for p in pairs if split-window<=p['seconds']<split]
        after=[p for p in pairs if split<=p['seconds']<split+window]
        if not before or not after:
            continue
        left=sum(p['speed']*p['dt'] for p in before)/sum(p['dt'] for p in before)
        right=sum(p['speed']*p['dt'] for p in after)/sum(p['dt'] for p in after)
        ratio=max(left,right)/(min(left,right)+.1)
        if min(left,right)>.3 and ratio>=options['change_ratio']:
            raw_regions.append({'start_seconds':float(split-window),'end_seconds':float(split+window),
                                'kinds':['speed_change'],'evidence':[{'before_speed':left,'after_speed':right,'ratio':ratio}]})
    # Merge overlapping detections; distinct candidate selections therefore do not fight each other.
    merged=[]
    for region in sorted(raw_regions,key=lambda r:r['start_seconds']):
        if merged and region['start_seconds']<=merged[-1]['end_seconds']:
            previous_region=merged[-1]
            previous_region['end_seconds']=max(previous_region['end_seconds'],region['end_seconds'])
            previous_region['kinds']=sorted(set(previous_region['kinds']+region['kinds']))
            previous_region['evidence'].extend(region['evidence'])
        else:
            merged.append(region)
    for region in merged:
        start,end=region['start_seconds'],region['end_seconds']
        within=[p for p in pairs if start<=p['seconds']<=end]
        middle=(start+end)/2
        left=[p['speed'] for p in within if p['seconds']<middle]
        right=[p['speed'] for p in within if p['seconds']>=middle]
        before=float(np.mean(left)) if left else 0.0
        after=float(np.mean(right)) if right else 0.0
        static=not within or all(p['mae']<.5 for p in within)
        kind='hold' if 'repeat_or_hold' in region['kinds'] else 'speed'
        amount=.35 if kind=='hold' else max(-2,min(2,2*(after-before)/(before+after+.1)))
        region.update(first_frame=min(range(len(times)),key=lambda i:abs(times[i]-start)),
                      last_frame=min(range(len(times)),key=lambda i:abs(times[i]-end)),
                      fully_static=static,proposal_kind=kind,proposal_amount=amount,
                      interpretation='suspicion_only_not_a_defect',before_speed=before,after_speed=after)
    return merged


def analyze_sources(clips,options=None):
    options=normalize_options(options)
    sources=[]
    for clip in clips:
        sha=file_hash(clip.path)
        regions=analyze_clip(clip,options)
        for region in regions:
            region['id']=region_id(sha,options,region)
        sources.append({'path':str(clip.path),'sha256':sha,'frame_count':len(clip.frames),
                        'duration_seconds':clip.duration,'regions':regions})
    payload={'version':VERSION,'options':options,'sources':sources}
    return dict(payload,analysis_id=digest(payload),default_selected=[],
                limitations='Repeat/hold and speed estimates are review hints. No shape repair or spatial stabilization.')


def load_selections(report_paths,clips,selected,excluded):
    if any(not isinstance(value,str) for value in list(selected)+list(excluded)):
        raise InputError('Motion region IDs must be strings')
    catalog={}
    clip_paths={str(c.path):i for i,c in enumerate(clips)}
    repeated_paths={str(c.path) for c in clips if sum(other.path==c.path for other in clips)>1}
    seen_reports=set()
    for path in report_paths:
        try:
            report=json.loads(Path(path).read_text(encoding='utf-8'))
            if report['version']!=VERSION:
                raise InputError('Unsupported motion-analysis version')
            options=normalize_options(report['options'])
            payload={key:report[key] for key in ['version','options','sources']}
            if digest(payload)!=report['analysis_id']:
                raise InputError('Motion-analysis integrity mismatch; regenerate the report')
            if report['analysis_id'] in seen_reports:
                continue
            seen_reports.add(report['analysis_id'])
            for source in report['sources']:
                ci=clip_paths.get(str(Path(source['path']).resolve()))
                if ci is not None and file_hash(clips[ci].path)!=source['sha256']:
                    raise InputError('Stale motion report: source SHA-256 changed')
                for region in source['regions']:
                    if region['id']!=region_id(source['sha256'],options,region):
                        raise InputError('Motion region ID does not match its source/options')
                    if region['id'] in catalog:
                        raise InputError('Duplicate region ID across motion reports')
                    catalog[region['id']]={'clip_index':ci,'ambiguous_input':source['path'] in repeated_paths,'source_sha256':source['sha256'],
                        'analysis_id':report['analysis_id'],'region':region}
        except (OSError,ValueError,TypeError,KeyError) as exc:
            raise InputError(f'Invalid motion report {path}: {exc}') from exc
    unknown=(set(selected)|set(excluded))-set(catalog)
    if unknown:
        raise InputError(f'Unknown motion region IDs: {sorted(unknown)}')
    chosen=[catalog[key] for key in selected if key not in excluded]
    for item in chosen:
        if item['ambiguous_input']:
            raise InputError('Selected region source appears more than once in the input sequence')
        if item['clip_index'] is None:
            raise InputError('Selected region source is not an input clip')
    by_clip={}
    for item in chosen:
        ci=item['clip_index'];region=item['region']
        spans=by_clip.setdefault(ci,[])
        if any(region['start_seconds']<end and region['end_seconds']>start for start,end in spans):
            raise InputError('Selected internal motion regions overlap')
        spans.append((region['start_seconds'],region['end_seconds']))
    return catalog,chosen


def apply_region(mapping,region,*,enabled=True):
    if not enabled:
        return 'clip_correction_disabled'
    if region['fully_static']:
        return 'fully_static_no_new_motion'
    start,end=region['start_seconds'],region['end_seconds']
    if start<mapping.protect-1e-9:
        return 'protected_interval_priority'
    if not 0<=start<end<=mapping.source_end+1e-9:
        raise InputError('Internal region is outside the source displayed timeline')
    bound=1+2*abs(region['proposal_amount']) if region['proposal_kind']=='hold' else 1+.25*abs(region['proposal_amount'])
    if mapping.speed_bound()*bound>mapping.max_speed+1e-9:
        return 'composed_speed_limit'
    mapping.region_warps.append((start,end,region['proposal_kind'],region['proposal_amount']))
    return 'candidate_requires_visual_review'


def inspect_motion(paths,output,options=None):
    from .comparison import compare_boundaries
    from .pipeline import job_directory,validate_inputs
    from .tools import diagnose
    inputs=validate_inputs(paths,minimum=1)
    diagnose()
    with job_directory(output,inputs) as job:
        clips=[probe(p,f'clip_{i+1:02d}') for i,p in enumerate(inputs)]
        report=analyze_sources(clips,options)
        previews=[]
        for clip,source in zip(clips,report['sources']):
            for region in source['regions']:
                count=max(2,round(clip.duration*float(clip.fps)))
                base=TimeMap(clip.frames[-1]['source_seconds'],(count-1)/float(clip.fps),0,.5,1,False,count,clip.fps,12)
                original=select_schedule(clip,base)
                reason=apply_region(base,region)
                proposed=select_schedule(clip,base)
                first=max(0,math.floor(region['start_seconds']*float(clip.fps)))
                last=min(count,math.ceil(region['end_seconds']*float(clip.fps))+1)
                original,proposed=original[first:last],proposed[first:last]
                identifier=region['id']
                left=render_clips([clip],job.work,[original],prefix=f'{identifier}_original')
                right=render_clips([clip],job.work,[proposed],prefix=f'{identifier}_proposal')
                center=len(original)//2
                for data in [left,right]:
                    data['boundaries']=[{'output_frame':center}]
                comparison=compare_boundaries(job.work,left,right,
                    max(1/float(clip.fps),len(original)/float(clip.fps)/2),
                    prefixes=[f'{identifier}_original',f'{identifier}_proposal'],
                    output_prefix=identifier,labels=['original','proposal'])
                previews.append({'region_id':identifier,'reason':reason,
                    'changed_source_selections':sum(a!=b for a,b in zip(original,proposed)),
                    'selected_for_final':False,'comparison':comparison[0],
                    'original':left,'proposal':right})
        if any(file_hash(Path(s['path']))!=s['sha256'] for s in report['sources']):
            raise InputError('Source changed during internal motion inspection')
        report['stage']='B2-inspection'
        report['previews']=previews
        write_report(job.work/'motion_report.json',report)
    return job.root
