"""Strict version-1 jobs and the reusable CLI/UI configuration API."""
from fractions import Fraction
import json
import os
from pathlib import Path
import re
import tempfile

from .boundary import validate_options
from .errors import InputError
from .enhancements import normalize_enhancements
from .internal_motion import apply_region,digest,load_selections
from .pipeline import validate_inputs
from .probe import probe
from .report import file_hash
from .retime import retime
from .time_map import allocate_frames,build_map,number
from .tools import diagnose


def object_fields(value,allowed,required,label):
    if not isinstance(value,dict):
        raise InputError(f'{label} must be an object')
    unknown=set(value)-set(allowed);missing=set(required)-set(value)
    if unknown or missing:
        raise InputError(f'{label}: unknown keys {sorted(unknown)}, missing keys {sorted(missing)}')
    return value


def text(value,label):
    if not isinstance(value,str) or not value.strip():
        raise InputError(f'{label} must be a nonempty string')
    return value


def boolean(value,label):
    if not isinstance(value,bool):
        raise InputError(f'{label} must be boolean')
    return value


def path_value(value,base,label):
    path=Path(text(value,label)).expanduser()
    return str((base/path).resolve() if not path.is_absolute() else path.resolve())


def identifiers(value,label):
    if not isinstance(value,list) or any(not isinstance(v,str) or not v for v in value):
        raise InputError(f'{label} must be an array of nonempty strings')
    if len(set(value))!=len(value):
        raise InputError(f'{label} contains duplicate IDs')
    return list(value)


def normalize_job(data,base_dir):
    base=Path(base_dir).resolve()
    object_fields(data,['schema_version','output','clips','boundaries','internal_motion','enhancements','narration','independent_clips'],
                  ['schema_version','output','clips'],'job')
    if isinstance(data['schema_version'],bool) or data['schema_version']!=1:
        raise InputError('schema_version must be integer 1')
    if not isinstance(data['schema_version'],int):
        raise InputError('schema_version must be integer 1')
    out=object_fields(data['output'],['directory','fps','audio_mode'],['directory'],'output')
    audio=out.get('audio_mode','preserve')
    # Older job files used remove_speech; keep their audio and avoid inference.
    if audio=='remove_speech':audio='preserve'
    if audio not in ('preserve','mute'):
        raise InputError('output.audio_mode must be preserve or mute')
    fps=out.get('fps')
    if fps is not None:
        fps=number(fps,'output.fps',positive=True)
        if not 1<=fps<=120:
            raise InputError('output.fps must be between 1 and 120')
    raw_output=Path(text(out['directory'],'output.directory')).expanduser()
    if (base/raw_output).is_symlink():
        raise InputError('Output must not be an existing symlink')
    output=dict(directory=path_value(out['directory'],base,'output.directory'),fps=fps,audio_mode=audio)
    independent=boolean(data.get('independent_clips',False),'independent_clips')
    minimum=1 if independent else 2
    if not isinstance(data['clips'],list) or len(data['clips'])<minimum:
        raise InputError(f'clips must be an ordered array of at least {minimum} clip(s)')
    clips=[];ids=[]
    for index,value in enumerate(data['clips']):
        item=object_fields(value,['id','path','target_seconds','protect_seconds','max_speed','ramp_seconds','correction_enabled'],
                           ['id','path','target_seconds'],f'clips[{index}]')
        identifier=text(item['id'],'clip.id')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',identifier) or identifier.startswith(('baseline','corrected','comparison')) or identifier.endswith('_diagnostic'):
            raise InputError('Clip IDs require 1..48 ASCII letters/digits/_/- and must avoid reserved output names')
        if identifier in ids:
            raise InputError(f'Duplicate clip ID: {identifier}')
        ids.append(identifier)
        clips.append(dict(id=identifier,path=path_value(item['path'],base,'clip.path'),
            target_seconds=number(item['target_seconds'],'target_seconds',positive=True),
            protect_seconds=number(item.get('protect_seconds',1),'protect_seconds'),
            max_speed=number(item.get('max_speed',12),'max_speed',minimum=1),
            ramp_seconds=number(item.get('ramp_seconds',.5),'ramp_seconds',positive=True),
            correction_enabled=boolean(item.get('correction_enabled',True),'correction_enabled')))
    boundaries=[dict(**{'from':a,'to':b},enabled=True,mode='manual',window_seconds=.5,strength=.3,
                     local_speed=False,duplicate_policy='review') for a,b in zip(ids,ids[1:])]
    supplied=data.get('boundaries',[])
    if not isinstance(supplied,list):
        raise InputError('boundaries must be an array')
    previous=-1
    for value in supplied:
        item=object_fields(value,['from','to','enabled','mode','window_seconds','strength','local_speed','duplicate_policy'],
                           ['from','to'],'boundary')
        left,right=text(item['from'],'boundary.from'),text(item['to'],'boundary.to')
        if left not in ids or right not in ids or ids.index(right)!=ids.index(left)+1:
            raise InputError('Boundary must reference adjacent clips in playback order')
        index=ids.index(left)
        if index<=previous:
            raise InputError('Boundary definitions must be unique and in playback order')
        previous=index
        window=number(item.get('window_seconds',.5),'window_seconds',positive=True)
        strength=number(item.get('strength',.3),'strength')
        validate_options(2,window,strength,[],[])
        mode=item.get('mode','manual')
        if mode!='manual':
            raise InputError('Only manual boundary mode is supported')
        duplicate=item.get('duplicate_policy','review')
        if duplicate not in ['review','keep','remove']:
            raise InputError('duplicate_policy must be review, keep, or remove')
        boundaries[index]=dict(**{'from':left,'to':right},mode=mode,
            enabled=boolean(item.get('enabled',True),'boundary.enabled'),window_seconds=window,strength=strength,
            local_speed=boolean(item.get('local_speed',False),'boundary.local_speed'),duplicate_policy=duplicate)
    motion=object_fields(data.get('internal_motion',{}),['reports','selected_ids','excluded_ids'],[],'internal_motion')
    reports=motion.get('reports',[])
    if not isinstance(reports,list):
        raise InputError('internal_motion.reports must be an array')
    motion=dict(reports=[path_value(p,base,'motion report') for p in reports],
                selected_ids=identifiers(motion.get('selected_ids',[]),'selected_ids'),
                excluded_ids=identifiers(motion.get('excluded_ids',[]),'excluded_ids'))
    narration_raw=object_fields(data.get('narration',{}),
        ['audio_path','subtitle_srt','source_timing_srt','timing_detail_csv','shot_mapping_csv','subtitle_style'],[],'narration')
    narration={key:(path_value(narration_raw[key],base,f'narration.{key}')
                    if narration_raw.get(key) is not None else None)
               for key in ('audio_path','subtitle_srt','shot_mapping_csv')}
    for key in ('audio_path','subtitle_srt','shot_mapping_csv'):
        narration.setdefault(key,None)
    from .narration import normalize_subtitle_style
    narration['subtitle_style']=normalize_subtitle_style(narration_raw.get('subtitle_style'))
    if narration['subtitle_style']['font_path']:
        narration['subtitle_style']['font_path']=path_value(
            narration['subtitle_style']['font_path'],base,'narration.subtitle_style.font_path')
    if independent and any(narration.get(key) for key in ('audio_path','subtitle_srt','shot_mapping_csv')):
        raise InputError('Narration is unavailable when clips are processed independently')
    if independent and (motion['selected_ids'] or motion['excluded_ids']):
        raise InputError('Clear selected and excluded motion regions before processing clips independently')
    return dict(schema_version=1,output=output,clips=clips,boundaries=boundaries,independent_clips=independent,internal_motion=motion,
                enhancements=normalize_enhancements(data.get('enhancements')),narration=narration)


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise InputError(f'Duplicate JSON object key: {key}')
        result[key]=value
    return result


def load_job(path):
    path=Path(path).expanduser().resolve()
    try:
        data=json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=_unique_object,
                        parse_constant=lambda value: (_ for _ in ()).throw(InputError(f'Non-finite JSON value: {value}')))
    except (OSError,ValueError) as exc:
        raise InputError(f'Cannot load job {path}: {exc}') from exc
    return normalize_job(data,path.parent)


def validate_job(config,output_override=None):
    """Read-only feasibility/provenance checks; never create an output directory."""
    config=normalize_job(config,Path.cwd())
    if output_override is not None:
        if Path(output_override).expanduser().is_symlink():
            raise InputError('Output override must not be a symlink')
        config['output']['directory']=str(Path(output_override).expanduser().resolve())
    paths=validate_inputs([c['path'] for c in config['clips']],minimum=1 if config['independent_clips'] else 2)
    output=Path(config['output']['directory'])
    if output.exists() or output.is_symlink() or any(output==p or output in p.parents for p in paths):
        raise InputError('Output already exists or conflicts with an input; choose a new directory')
    tools=diagnose()
    clips=[probe(p,c['id']) for p,c in zip(paths,config['clips'])]
    fps=Fraction(str(config['output']['fps'])) if config['output']['fps'] is not None else clips[0].fps
    budgets=allocate_frames([c['target_seconds'] for c in config['clips']],fps)
    from .narration import validate_narration
    validate_narration(config['narration'],config['clips'],duration=sum(budgets)/float(fps),tolerance=1/float(fps)+.001)
    maps=[build_map(clip,item['target_seconds'],item['protect_seconds'],item['max_speed'],item['ramp_seconds'],n,fps,
                    enabled=item['correction_enabled']) for clip,item,n in zip(clips,config['clips'],budgets)]
    motion=config['internal_motion']
    _,chosen=load_selections(motion['reports'],clips,motion['selected_ids'],motion['excluded_ids'])
    for item in chosen:
        ci=item['clip_index']
        apply_region(maps[ci],item['region'],enabled=config['clips'][ci]['correction_enabled'])
    return config,dict(status='valid',output_fps=str(fps),budget_frames=budgets,total_frames=sum(budgets),
                       tools=tools,config_sha256=digest(config),
                       input_sha256=[file_hash(p) for p in paths])


def save_job(config,path,*,overwrite=False):
    """Save relative paths when possible, absolute paths across Windows drives."""
    normalized=normalize_job(config,Path.cwd())
    path=Path(path).expanduser().absolute()
    dependencies=[Path(c['path']) for c in normalized['clips']]+[Path(p) for p in normalized['internal_motion']['reports']]
    dependencies += [Path(normalized['narration'][key]) for key in ('audio_path','subtitle_srt','shot_mapping_csv')
                     if normalized['narration'][key]]
    font_path=normalized['narration']['subtitle_style']['font_path']
    if font_path:dependencies.append(Path(font_path))
    if path.resolve() in dependencies:
        raise InputError('Cannot replace an input clip or motion report with a job file')
    value=json.loads(json.dumps(normalized))
    def saved_path(source):
        try:
            return os.path.relpath(source,path.parent)
        except ValueError:
            # Windows cannot express a relative path between different drives.
            return source
    for item in value['clips']:
        item['path']=saved_path(item['path'])
    value['output']['directory']=saved_path(value['output']['directory'])
    value['internal_motion']['reports']=[saved_path(p) for p in value['internal_motion']['reports']]
    style=value['narration']['subtitle_style']
    if style['font_path']:style['font_path']=saved_path(style['font_path'])
    value['narration']={key:(saved_path(item) if item else None) for key,item in value['narration'].items()
                        if key!='subtitle_style'}
    value['narration']['subtitle_style']=style
    serialized=json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n'
    path.parent.mkdir(parents=True,exist_ok=True)
    if not overwrite:
        try:
            with path.open('x',encoding='utf-8') as stream:
                stream.write(serialized)
        except OSError as exc:
            raise InputError(f'Cannot save job {path}: {exc}') from exc
    else:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
            stream.write(serialized);temporary=Path(stream.name)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    return path


def run_job(path_or_config,output_override=None):
    from_path=isinstance(path_or_config,(str,Path))
    config=load_job(path_or_config) if from_path else normalize_job(path_or_config,Path.cwd())
    config,validation=validate_job(config,output_override)
    clips=config['clips'];motion=config['internal_motion']
    definition=dict(schema_version=1,config=config,config_sha256=validation['config_sha256'],
                    source_json=str(Path(path_or_config).resolve()) if from_path else None,
                    source_json_sha256=file_hash(Path(path_or_config)) if from_path else None)
    if config['independent_clips']:
        import shutil
        from .pipeline import job_directory
        from .report import write_report
        paths=[Path(c['path']) for c in clips]
        with job_directory(config['output']['directory'],paths) as job:
            timeline=[];outputs=[];enhancement_audits=[]
            for clip in clips:
                child=job.work/f'.clip-{clip["id"]}'
                child_root=retime([clip['path']],child,targets=[clip['target_seconds']],
                    protect=[clip['protect_seconds']],max_speed=[clip['max_speed']],ramp=[clip['ramp_seconds']],
                    disabled_clips=[1] if not clip['correction_enabled'] else [],boundary_options=[],
                    clip_ids=[clip['id']],output_fps=config['output']['fps'],audio_mode=config['output']['audio_mode'],
                    enhancements=config['enhancements'],independent_clip=True)
                child_report=json.loads((child_root/'results/report.json').read_text(encoding='utf-8'))
                source=child_root/'results'/f'{clip["id"]}.mp4'
                destination=job.work/f'{clip["id"]}.mp4'
                shutil.move(str(source),str(destination))
                from .stills import save_last_frame
                still_name=f'{clip["id"]}_last_frame.png'
                save_last_frame(destination,job.work/still_name)
                entry=dict(child_report['timeline'][0],file=f'{clip["id"]}.mp4')
                entry['last_frame_image']=still_name
                timeline.append(entry);outputs.append(dict(clip_id=clip['id'],file=entry['file'],
                    last_frame_image=still_name,requested_seconds=entry['requested_seconds'],
                    measured_seconds=entry['measured_clip_seconds']))
                enhancement_audits.extend(child_report.get('corrected',{}).get('enhancements',[]))
                shutil.rmtree(child_root)
            total=sum(item['measured_clip_seconds'] for item in timeline)
            write_report(job.work/'report.json',dict(stage='C',independent_clips=True,
                quality_status='technical_candidate_real_visual_quality_unverified',audio_mode=config['output']['audio_mode'],
                job_definition=definition,individual_outputs=outputs,timeline=timeline,comparisons=[],
                corrected={'enhancements':enhancement_audits},
                timeline_validation=dict(status='passed',requested_total_seconds=sum(c['target_seconds'] for c in clips),
                    measured_total_seconds=total,error_seconds=total-sum(c['target_seconds'] for c in clips),
                    separate_files=True,joined_video_created=False)))
        return job.root
    return retime([c['path'] for c in clips],config['output']['directory'],
        targets=[c['target_seconds'] for c in clips],protect=[c['protect_seconds'] for c in clips],
        max_speed=[c['max_speed'] for c in clips],ramp=[c['ramp_seconds'] for c in clips],
        disabled_clips=[i+1 for i,c in enumerate(clips) if not c['correction_enabled']],
        boundary_options=config['boundaries'],clip_ids=[c['id'] for c in clips],output_fps=config['output']['fps'],
        audio_mode=config['output']['audio_mode'],motion_reports=motion['reports'],
        selected_regions=motion['selected_ids'],excluded_regions=motion['excluded_ids'],job_definition=definition,
        enhancements=config['enhancements'],narration=config['narration'])
