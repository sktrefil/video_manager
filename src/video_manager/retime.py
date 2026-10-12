"""B1 protected retiming pipeline and measured F4 timeline validation."""
from fractions import Fraction
from pathlib import Path
import re
import copy

from .boundary import analyze_boundaries, correction_schedules, validate_options
from .comparison import compare_boundaries
from .errors import InputError
from .pipeline import job_directory, validate_inputs
from .probe import probe
from .render import boundary_segments, render_clips
from .report import file_hash, write_report
from .time_map import add_boundary_warp, allocate_frames, build_map, number, select_schedule
from .tools import diagnose, run_tool


def expand_setting(value, count, label):
    values = value if isinstance(value, (list, tuple)) else [value]
    if len(values)==1:
        return list(values)*count
    if len(values)!=count:
        raise InputError(f'{label} must contain one value or one value per clip')
    return list(values)


def validate_rendered(path, expected, fps):
    video=probe(path,path.stem)
    if len(video.frames)!=expected:
        raise InputError(f'{path.name}: decoded frame count does not match budget')
    if video.has_audio:
        raise InputError(f'{path.name}: unexpected audio in muted output')
    for i,frame in enumerate(video.frames):
        if abs(frame['source_seconds']-i/float(fps))>max(float(video.time_base),1e-6):
            raise InputError(f'{path.name}: decoded PTS has a gap or overlap')
    if abs(video.duration-expected/float(fps))>float(1/fps):
        raise InputError(f'{path.name}: decoded duration differs from frame budget')
    return video


def export_clip_outputs(output,result):
    fps=Fraction(result['fps'])
    items=[]
    for clip_range in result['clip_ranges']:
        start,end=clip_range['start_frame'],clip_range['end_frame']
        names=[]
        for diagnostic in [False,True]:
            suffix='_diagnostic' if diagnostic else ''
            name=f"{clip_range['clip_id']}{suffix}.mp4"
            run_tool(['ffmpeg','-v','error','-nostdin','-n','-i',str(output/f'corrected{suffix}.mp4'),
                '-vf',f'trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS',
                '-an','-r',str(fps),'-fps_mode','cfr','-c:v','libx264','-threads','2',
                '-crf','18','-pix_fmt','yuv420p',str(output/name)],timeout=180)
            measured=validate_rendered(output/name,end-start,fps)
            names.append(name)
        items.append(dict(clip_id=clip_range['clip_id'],start_frame=start,end_frame=end,
                          start_seconds=start/float(fps),end_seconds=end/float(fps),
                          measured_clip_seconds=measured.duration,files=names))
    return items


def retime(paths, output, *, targets, protect=1.0, max_speed=12.0, ramp=0.5,
           local_speed=False, remove_duplicates=False, window=0.5, strength=0.3,
           disabled_clips=(),disabled_boundaries=(),audio_mode='mute',
           motion_reports=(),selected_regions=(),excluded_regions=(),
           clip_ids=None,output_fps=None,boundary_options=None,job_definition=None):
    inputs=validate_inputs(paths)
    count=len(inputs)
    targets=expand_setting(targets,count,'targets')
    protects=expand_setting(protect,count,'protect')
    limits=expand_setting(max_speed,count,'max_speed')
    ramps=expand_setting(ramp,count,'ramp')
    validate_options(count,window,strength,disabled_clips,disabled_boundaries)
    if audio_mode!='mute':
        raise InputError('Audio preservation is not supported during retiming; use mute')
    if not isinstance(local_speed,bool) or not isinstance(remove_duplicates,bool):
        raise InputError('Correction enable flags must be boolean')
    if output_fps is not None:
        output_fps=number(output_fps,'output_fps',positive=True)
        if not 1<=output_fps<=120:
            raise InputError('output_fps must be between 1 and 120')
    if clip_ids is not None and any(not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',identifier) or identifier.startswith(('baseline','corrected','comparison')) or identifier.endswith('_diagnostic') for identifier in clip_ids):
        raise InputError('Clip IDs contain unsafe or reserved output names')
    tools=diagnose()
    with job_directory(output,inputs) as job:
        if job_definition is not None:
            write_report(job.work/'executed_job.json',job_definition['config'])
        hashes=[file_hash(path) for path in inputs]
        ids=clip_ids or [f'clip_{i+1:02d}' for i in range(count)]
        if len(ids)!=count or len(set(ids))!=count:
            raise InputError('Clip IDs must be unique and match input count')
        clips=[probe(path,identifier) for path,identifier in zip(inputs,ids)]
        fps=Fraction(str(output_fps)) if output_fps is not None else clips[0].fps
        budgets=allocate_frames(targets,fps)
        maps=[build_map(c,t,p,m,r,n,fps,enabled=i+1 not in disabled_clips)
              for i,(c,t,p,m,r,n) in enumerate(zip(clips,targets,protects,limits,ramps,budgets))]
        settings=boundary_options or [dict(window_seconds=window,strength=strength,local_speed=local_speed,
            enabled=i+1 not in disabled_boundaries,duplicate_policy='remove' if remove_duplicates else 'review')
            for i in range(count-1)]
        if len(settings)!=count-1:
            raise InputError('Boundary option count must match adjacent clip pairs')
        measurements,decisions=[],[]
        for index,setting in enumerate(settings):
            validate_options(2,setting['window_seconds'],setting['strength'],[],[])
            measured_pair=analyze_boundaries(clips[index:index+2],setting['window_seconds'])
            effective=copy.deepcopy(measured_pair)
            source_before=measured_pair[0]['before']['speed']
            source_after=measured_pair[0]['after']['speed']
            effective[0]['before']['speed']*=maps[index].base_speed(maps[index].output_end)
            effective[0]['after']['speed']*=maps[index+1].base_speed(0)
            _,pair_decisions=correction_schedules(clips[index:index+2],effective,
                window=setting['window_seconds'],strength=setting['strength'],local_speed=setting['local_speed'],
                remove_duplicates=False,disabled_clips=[j+1 for j in range(2) if index+j+1 in disabled_clips],
                disabled_boundaries=[] if setting['enabled'] and index+1 not in disabled_boundaries else [1])
            plan=pair_decisions[0]
            plan['velocity_planning']=dict(source_before=source_before,source_after=source_after,
                effective_before=effective[0]['before']['speed'],effective_after=effective[0]['after']['speed'],
                method='base_retiming_seam_derivatives')
            if plan['speed_applied'] and maps[index+1].protect>0:
                left_speed=effective[0]['before']['speed'];right_speed=effective[0]['after']['speed']
                plan['left_alpha']=setting['strength']*max(-.8,min(.8,right_speed/left_speed-1))
                plan['velocity_planning'].update(target=right_speed,reason='right_head_protected_match_fixed_right')
            measured_pair[0]['boundary']=index+1
            pair_decisions[0]['boundary']=index+1
            measurements.extend(measured_pair);decisions.extend(pair_decisions)
        for index,decision in enumerate(decisions):
            duplicate_requested=settings[index]['duplicate_policy']=='remove'
            decision['duplicate_removal_requested']=duplicate_requested
            decision['duplicate_removed']=False
            decision['duplicate_reason']=decision['exclusion_reason'] or (
                'fixed_budget_endpoint_and_protection_priority' if duplicate_requested else 'not_requested')
            if decision['speed_applied']:
                side_results={}
                for ci,side,prefix in [(index,'tail','left'),(index+1,'head','right')]:
                    side_results[prefix]=add_boundary_warp(maps[ci],side,
                        decision[f'{prefix}_window_seconds'],decision[f'{prefix}_alpha'])
                decision['side_results']=side_results
                decision['speed_applied']=any(v=='candidate_requires_visual_review' for v in side_results.values())
                if not decision['speed_applied']:
                    decision['speed_reason']='composition_constraints_excluded'
        from .internal_motion import apply_region,load_selections
        catalog,chosen=load_selections(motion_reports,clips,selected_regions,excluded_regions)
        motion_decisions=[]
        chosen_ids={item['region']['id'] for item in chosen}
        for identifier,item in catalog.items():
            region=item['region'];ci=item['clip_index']
            if identifier not in chosen_ids:
                motion_decisions.append(dict(region_id=identifier,applied=False,
                    reason='explicitly_excluded' if identifier in excluded_regions else 'not_selected'))
                continue
            before=select_schedule(clips[ci],maps[ci])
            reason=apply_region(maps[ci],region,enabled=ci+1 not in disabled_clips)
            after=select_schedule(clips[ci],maps[ci])
            changed=sum(a!=b for a,b in zip(before,after))
            if reason=='candidate_requires_visual_review' and not changed:
                reason='no_effect_after_frame_quantization'
            motion_decisions.append(dict(region_id=identifier,clip_id=clips[ci].id,
                analysis_id=item['analysis_id'],source_sha256=item['source_sha256'],
                applied=bool(changed),reason=reason,changed_source_selections=changed))
        schedules=[select_schedule(c,m) for c,m in zip(clips,maps)]
        reference=render_clips(clips,job.work,output_fps=fps)
        candidate=render_clips(clips,job.work,schedules=schedules,prefix='corrected',output_fps=fps)
        windows=[s['window_seconds'] for s in settings]
        boundary_segments(job.work,reference,window=window,windows=windows)
        boundary_segments(job.work,candidate,prefix='corrected',window=window,windows=windows)
        comparisons=compare_boundaries(job.work,reference,candidate,window,windows=windows)
        measured=validate_rendered(job.work/'corrected.mp4',sum(budgets),fps)
        validate_rendered(job.work/'corrected_diagnostic.mp4',sum(budgets),fps)
        timeline=export_clip_outputs(job.work,candidate)
        for index,item in enumerate(timeline):
            item.update(requested_seconds=targets[index],budget_frames=budgets[index],
                        actual_seconds=budgets[index]/float(fps),
                        error_seconds=item['measured_clip_seconds']-targets[index],
                        mapping=maps[index].describe(),correction_enabled=index+1 not in disabled_clips)
            if abs(item['error_seconds'])>float(1/fps)+1e-6:
                raise InputError('Per-clip target error exceeds one frame')
        total_error=measured.duration-sum(targets)
        if abs(total_error)>float(1/fps)+1e-6:
            raise InputError('Total target error exceeds one frame')
        if any(file_hash(p)!=sha for p,sha in zip(inputs,hashes)):
            raise InputError('An input changed during processing')
        write_report(job.work/'report.json',dict(stage='C' if job_definition else 'B2' if motion_reports else 'B1',tools=tools,audio_mode='mute',
            job_definition=job_definition,
            quality_status='technical_candidate_real_visual_quality_unverified',
            internal_motion=dict(reports=[str(p) for p in motion_reports],selected=list(selected_regions),
                excluded=list(excluded_regions),decisions=motion_decisions),
            settings=dict(targets=targets,protect=protects,max_speed=limits,ramp=ramps,window=window,
                          strength=strength,local_speed=local_speed,remove_duplicates=remove_duplicates,
                          disabled_clips=list(disabled_clips),disabled_boundaries=list(disabled_boundaries),
                          output_fps=str(fps),boundary_options=settings),
            clips=[dict(c.metadata(),sha256=sha) for c,sha in zip(clips,hashes)],
            source_measurements=measurements,decisions=decisions,baseline=reference,corrected=candidate,
            comparisons=comparisons,timeline=timeline,
            timeline_validation=dict(status='passed',requested_total_seconds=sum(targets),
                budget_frames=sum(budgets),decoded_frames=len(measured.frames),
                measured_total_seconds=measured.duration,error_seconds=total_error,
                contiguous_ranges=True,pts_valid=True,duplicate_policy='retain_shared_endpoints_to_preserve_constraints')))
    return job.root
