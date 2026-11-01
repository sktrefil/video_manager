"""Validate narration assets and compose them only during an explicit render job."""
import csv
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

from .errors import InputError
from .report import file_hash
from .timing_reference import clip_key
from .tools import run_tool

KEYS=('audio_path','subtitle_srt','shot_mapping_csv')
DEFAULT_SUBTITLE_STYLE=dict(font='Malgun Gothic',font_path=None,size=34,position='bottom',
    vertical_position=88,alignment='center',margin=48,background=False,background_color='#000000',
    background_opacity=55,text_color='#FFFFFF',outline=True,outline_size=2,bold=True)


def normalize_subtitle_style(value=None):
    value={} if value is None else value
    if not isinstance(value,dict) or set(value)-set(DEFAULT_SUBTITLE_STYLE):
        raise InputError('Invalid subtitle style fields')
    style=dict(DEFAULT_SUBTITLE_STYLE,**value)
    if 'vertical_position' not in value:
        style['vertical_position']={'top':12,'middle':50,'bottom':88}.get(style.get('position'),88)
    font=style['font']
    if not isinstance(font,str) or not 1<=len(font.strip())<=80 or any(c in font for c in ",':;\\\n\r"):
        raise InputError('Subtitle font must be a plain font family name')
    style['font']=font.strip()
    font_path=style['font_path']
    if font_path is not None and (not isinstance(font_path,str) or not font_path.strip()):
        raise InputError('Subtitle font_path must be a font file path or null')
    for key,lower,upper in [('size',8,96),('margin',0,400),('background_opacity',0,100),('outline_size',0,8)]:
        v=style[key]
        if isinstance(v,bool) or not isinstance(v,int) or not lower<=v<=upper:
            raise InputError(f'Subtitle {key} must be an integer from {lower} to {upper}')
    if isinstance(style['vertical_position'],bool) or not isinstance(style['vertical_position'],int) or not 5<=style['vertical_position']<=95:
        raise InputError('Subtitle vertical_position must be an integer from 5 to 95')
    if style['position'] not in ('bottom','middle','top'):
        raise InputError('Subtitle position must be bottom, middle, or top')
    if style['alignment'] not in ('left','center','right'):
        raise InputError('Subtitle alignment must be left, center, or right')
    if not isinstance(style['background'],bool):raise InputError('Subtitle background must be boolean')
    if not isinstance(style['outline'],bool) or not isinstance(style['bold'],bool):
        raise InputError('Subtitle outline and bold must be boolean')
    if not isinstance(style['text_color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',style['text_color']):
        raise InputError('Subtitle text_color must be #RRGGBB')
    if not isinstance(style['background_color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',style['background_color']):
        raise InputError('Subtitle background_color must be #RRGGBB')
    return style


def _ass_colour(hex_colour,opacity=100):
    red,green,blue=(int(hex_colour[i:i+2],16) for i in (1,3,5))
    alpha=round(255*(100-opacity)/100)
    return f'&H{alpha:02X}{blue:02X}{green:02X}{red:02X}'


def subtitle_filter(style,fontsdir=None,filename='narration.ass'):
    style=normalize_subtitle_style(style)
    column={'left':1,'center':2,'right':3}[style['alignment']]
    row=6 if style['vertical_position']<34 else 3 if style['vertical_position']<67 else 0
    alignment=row+column
    parts=[f"FontName={style['font']}",f"FontSize={style['size']}",f'Alignment={alignment}',
           f"MarginV={style['margin']}",f"MarginL={style['margin']}",f"MarginR={style['margin']}",
           f"PrimaryColour={_ass_colour(style['text_color'])}",
           f"Bold={-1 if style['bold'] else 0}"]
    parts+=([f"Outline={style['outline_size']}",'OutlineColour=&H00000000'] if style['outline'] else ['Outline=0'])
    if style['background']:
        parts+=['BorderStyle=3',f"BackColour={_ass_colour(style['background_color'],style['background_opacity'])}",'Shadow=0']
    else:parts+=['BorderStyle=1','Shadow=0']
    options='fontsdir=fonts:' if fontsdir else ''
    return f"subtitles={filename}:"+options+"force_style='"+','.join(parts)+"'"


def _ass_time(value):
    centiseconds=round(float(value)*100)
    hours,centiseconds=divmod(centiseconds,360000)
    minutes,centiseconds=divmod(centiseconds,6000)
    seconds,centiseconds=divmod(centiseconds,100)
    return f'{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}'


def write_positioned_ass(source,destination,style,width,height):
    """Convert SRT cues to positioned ASS so the vertical slider is exact."""
    import html
    style=normalize_subtitle_style(style)
    x={'left':style['margin'],'center':width//2,'right':width-style['margin']}[style['alignment']]
    y=round(height*style['vertical_position']/100)
    lines=[
        '[Script Info]','ScriptType: v4.00+','WrapStyle: 2',
        f'PlayResX: {width}',f'PlayResY: {height}','ScaledBorderAndShadow: yes','',
        '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        f"Style: Default,{style['font']},{style['size']},{_ass_colour(style['text_color'])},&H000000FF,&H00000000,{_ass_colour(style['background_color'],style['background_opacity'])},{-1 if style['bold'] else 0},0,{3 if style['background'] else 1},{style['outline_size'] if style['outline'] else 0},0,{(6 if style['vertical_position']<34 else 3 if style['vertical_position']<67 else 0)+{'left':1,'center':2,'right':3}[style['alignment']]},{style['margin']},{style['margin']},{style['margin']},1",
        '','[Events]',
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for cue in read_subtitles(source):
        text=html.unescape(cue['text']).replace('\\','\\\\').replace('{','\\{').replace('}','\\}')
        for tag,ass in (('<i>','{\\i1}'),('</i>','{\\i0}'),('<b>','{\\b1}'),('</b>','{\\b0}'),
                        ('<u>','{\\u1}'),('</u>','{\\u0}')):
            text=text.replace(tag,ass)
        text=text.replace('\n','\\N')
        if style['bold']:text='{\\b1}'+text
        lines.append(f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Default,,0,0,0,,{{\\pos({x},{y})}}{text}")
    Path(destination).write_text('\n'.join(lines)+'\n',encoding='utf-8')


def seconds(value):
    match=re.fullmatch(r'(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})',value.strip())
    if not match:raise InputError(f'Invalid SRT timestamp: {value}')
    h,m,s,ms=map(int,match.groups())
    return h*3600+m*60+s+ms/1000


def read_subtitles(path):
    cues=[];seen=set()
    for block in re.split(r'\n\s*\n',Path(path).read_text(encoding='utf-8-sig').strip()):
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].isdigit() or ' --> ' not in lines[1]:
            raise InputError('SRT requires a number, start --> end, and subtitle text per block')
        identifier=int(lines[0]);a,b=lines[1].split(' --> ',1)
        start,end=seconds(a),seconds(b)
        if identifier in seen or end<=start or (cues and start<cues[-1]['end']-.001):
            raise InputError(f'SRT duplicate number, reversed time or overlap: {identifier}')
        seen.add(identifier)
        cues.append(dict(number=identifier,start=start,end=end,text='\n'.join(lines[2:])))
    if not cues:raise InputError('SRT is empty')
    return cues


def validate_narration(assets,clips,*,duration=None,tolerance=.05,probe_audio=True):
    assets=assets or {}
    style=normalize_subtitle_style(assets.get('subtitle_style'))
    if not any(assets.get(key) for key in KEYS):return None
    if not all(assets.get(key) for key in KEYS):
        raise InputError('TTS: select all three files: audio, final SRT, shot mapping CSV')
    paths={key:Path(assets[key]).resolve() for key in KEYS}
    if style['font_path']:
        font_path=Path(style['font_path']).resolve()
        if not font_path.is_file() or font_path.suffix.lower() not in ('.ttf','.otf','.ttc'):
            raise InputError('Custom subtitle font must be an existing TTF, OTF, or TTC file')
        style['font_path']=str(font_path);paths['font_path']=font_path
    for key,path in paths.items():
        suffixes=('.mp3','.wav') if key=='audio_path' else ('.srt',) if key=='subtitle_srt' else ('.csv',) if key=='shot_mapping_csv' else ('.ttf','.otf','.ttc')
        if not path.is_file() or path.suffix.lower() not in suffixes:
            raise InputError(f'TTS: missing file or incorrect file type: {path}')
    try:
        cues=read_subtitles(paths['subtitle_srt'])
        with paths['shot_mapping_csv'].open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            required={'shot','video_in_s','video_out_s','duration_s','subtitle_numbers'}
            if not required.issubset(reader.fieldnames or []):
                raise InputError('Shot CSV requires: '+', '.join(sorted(required)))
            rows=list(reader)
        if len(rows)!=len(clips):raise InputError('Shot CSV row count must match the video clip count')
        end=0.;seen=set();shots=[]
        for index,(row,clip) in enumerate(zip(rows,clips),1):
            shot=row['shot'].strip()
            try:expected=clip_key(clip['path'])[1]
            except InputError:expected=clip['id']
            if shot!=expected or shot in seen:
                raise InputError(f'Shot CSV row {index}: expected {expected}, found {shot}')
            seen.add(shot)
            start,finish,length=map(float,(row['video_in_s'],row['video_out_s'],row['duration_s']))
            if (not all(math.isfinite(v) for v in (start,finish,length)) or start<0 or length<=0
                    or abs(start-end)>tolerance or abs(finish-start-length)>tolerance
                    or abs(length-clip['target_seconds'])>tolerance):
                raise InputError(f'Shot CSV timing differs from clip Target: {shot}')
            numbers=[int(value.strip()) for value in row['subtitle_numbers'].split(',') if value.strip()]
            overlapping=[cue['number'] for cue in cues if cue['start']<finish and cue['end']>start]
            if len(numbers)!=len(set(numbers)) or set(numbers)!=set(overlapping):
                raise InputError(f'Shot CSV subtitle numbers do not match SRT overlaps: {shot}')
            end=finish;shots.append(dict(shot=shot,start=start,end=finish,subtitle_numbers=numbers))
        total=sum(c['target_seconds'] for c in clips) if duration is None else float(duration)
        if abs(end-total)>tolerance or cues[-1]['end']>total+tolerance:
            raise InputError('TTS: subtitle/shot timing exceeds or differs from the final video duration')
        plan=dict(paths={key:str(path) for key,path in paths.items()},cues=cues,shots=shots,subtitle_style=style,
                  duration=total,subtitle_count=len(cues),shot_count=len(shots),
                  alignment='whole_track_duration_fit; word_timing_not_verified',
                  hashes={key:file_hash(path) for key,path in paths.items()})
        if probe_audio:
            result=run_tool(['ffprobe','-v','error','-select_streams','a:0','-show_entries',
                'stream=duration:format=duration','-of','json',str(paths['audio_path'])])
            metadata=json.loads(result.stdout)
            if not metadata.get('streams'):raise InputError('TTS file has no audio stream')
            raw_duration=metadata['streams'][0].get('duration')
            if raw_duration in (None,'N/A',''):raw_duration=metadata.get('format',{}).get('duration',0)
            source=float(raw_duration)
            if not math.isfinite(source) or source<=0:raise InputError('Cannot determine TTS audio duration')
            ratio=source/total
            if not .5<=ratio<=2:raise InputError('TTS duration differs too much from video (allowed speed: 0.5–2x)')
            plan.update(source_seconds=source,tempo=ratio)
            filters=run_tool(['ffmpeg','-hide_banner','-filters']).stdout
            if not re.search(r'\bsubtitles\s',filters):raise InputError('FFmpeg subtitles filter (libass) is required')
        return plan
    except (OSError,UnicodeError,ValueError,KeyError,TypeError) as exc:
        raise InputError(f'Cannot read TTS/SRT/CSV: {exc}') from exc


def render_narration(work,plan,*,has_background,crf=18,progress=None):
    """Burn subtitles and mix duration-fitted narration; called by Run job only."""
    work=Path(work).resolve()
    for key,path in plan['paths'].items():
        if file_hash(Path(path))!=plan['hashes'][key]:raise InputError(f'TTS input changed: {path}')
    # Fixed relative filter filename avoids Windows drive/Unicode filter escaping.
    subtitle=work/'narration.srt'
    subtitle_ass=work/'narration.ass'
    subtitle.write_text(Path(plan['paths']['subtitle_srt']).read_text(encoding='utf-8-sig'),encoding='utf-8')
    dimensions=json.loads(run_tool(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height','-of','json',str(work/'corrected.mp4')]).stdout)['streams'][0]
    write_positioned_ass(plan['paths']['subtitle_srt'],subtitle_ass,plan['subtitle_style'],
                         int(dimensions['width']),int(dimensions['height']))
    if plan['subtitle_style'].get('font_path'):
        fonts=work/'fonts';fonts.mkdir(exist_ok=True)
        shutil.copyfile(plan['subtitle_style']['font_path'],fonts/Path(plan['subtitle_style']['font_path']).name)
    duration=plan['duration']
    chain=f'[1:a:0]asetpts=PTS-STARTPTS,atempo={plan["tempo"]:.12g},aresample=48000,apad,atrim=duration={duration:.9f}[tts]'
    if has_background:
        chain+=';[0:a:0]volume=0.35[bg];[bg][tts]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:latency=1[a]'
    else:chain+=';[tts]alimiter=limit=0.95:latency=1[a]'
    chain+=';[0:v:0]'+subtitle_filter(plan.get('subtitle_style'),
        fontsdir=bool(plan['subtitle_style'].get('font_path')),filename='narration.ass')+'[v]'
    if progress:progress('Mixing TTS and burning subtitles')
    target=work/'narrated.mp4'
    run_tool(['ffmpeg','-v','error','-nostdin','-n','-i',str(work/'corrected.mp4'),
        '-i',plan['paths']['audio_path'],'-filter_complex',chain,'-map','[v]','-map','[a]',
        '-c:v','libx264','-threads','2','-crf',str(crf),'-pix_fmt','yuv420p','-fps_mode','cfr',
        '-c:a','aac','-b:a','192k','-ar','48000','-t',f'{duration:.9f}',
        '-movflags','+faststart',str(target)],timeout=7200,cwd=str(work))
    for key,path in plan['paths'].items():
        if file_hash(Path(path))!=plan['hashes'][key]:raise InputError(f'TTS input changed during render: {path}')
    target.replace(work/'corrected.mp4')
    return dict(enabled=True,alignment=plan['alignment'],source_seconds=plan['source_seconds'],
        output_seconds=duration,tempo=plan['tempo'],subtitle_count=plan['subtitle_count'],
        shot_count=plan['shot_count'],background_gain=.35 if has_background else 0,
        subtitles='burned_in',subtitle_style=plan.get('subtitle_style',DEFAULT_SUBTITLE_STYLE),hashes=plan['hashes'])


def render_subtitle_preview(config,start,output,*,seconds=5):
    """Render a short source excerpt with the final subtitle style and fitted TTS."""
    import tempfile
    clips=config['clips']
    plan=validate_narration(config['narration'],clips)
    if plan is None:raise InputError('Select narration audio, SRT, and shot mapping first')
    start=float(start)
    if not math.isfinite(start) or not 0<=start<plan['duration']:
        raise InputError('Preview start must be within the final timeline')
    shot=next((s for s in plan['shots'] if s['start']<=start<s['end']),None)
    if shot is None:raise InputError('No mapped shot at preview start')
    length=min(float(seconds),plan['duration']-start,shot['end']-start)
    clip=clips[plan['shots'].index(shot)]
    source=Path(clip['path'])
    if not source.is_file():raise InputError(f'Missing preview clip: {source}')
    metadata=json.loads(run_tool(['ffprobe','-v','error','-show_entries','format=duration',
                                  '-of','json',str(source)]).stdout)
    source_duration=float(metadata['format']['duration'])
    if not math.isfinite(source_duration) or source_duration<=0:
        raise InputError('Cannot determine preview source duration')
    first=json.loads(run_tool(['ffprobe','-v','error','-select_streams','v:0',
                               '-show_entries','stream=width,height,sample_aspect_ratio',
                               '-of','json',clips[0]['path']]).stdout)['streams'][0]
    sar=first.get('sample_aspect_ratio','1:1').split(':')
    ratio=float(sar[0])/float(sar[1]) if len(sar)==2 and float(sar[1]) else 1
    width=max(2,round(int(first['width'])*ratio/2)*2)
    height=max(2,round(int(first['height'])/2)*2)
    source_start=min(max(0,(start-shot['start'])/clip['target_seconds']*source_duration),
                     max(0,source_duration-length))
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='subtitle-preview-') as temporary:
        work=Path(temporary)
        write_positioned_ass(plan['paths']['subtitle_srt'],work/'narration.ass',plan['subtitle_style'],width,height)
        if plan['subtitle_style'].get('font_path'):
            fonts=work/'fonts';fonts.mkdir(exist_ok=True)
            shutil.copyfile(plan['subtitle_style']['font_path'],fonts/Path(plan['subtitle_style']['font_path']).name)
        fit=(f'scale=trunc(iw*sar/2)*2:ih,setsar=1,'
             f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
             f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2')
        video=(f'[0:v:0]{fit},tpad=stop_mode=clone:stop_duration={length:.6f},'
               f'setpts=PTS-STARTPTS+{start:.6f}/TB,'+subtitle_filter(plan['subtitle_style'],
                   fontsdir=bool(plan['subtitle_style'].get('font_path')),filename='narration.ass')+
               f',setpts=PTS-STARTPTS,trim=duration={length:.6f}[v]')
        audio=(f'[1:a:0]asetpts=PTS-STARTPTS,atempo={plan["tempo"]:.12g},'
               f'atrim=start={start:.6f}:duration={length:.6f},asetpts=PTS-STARTPTS[a]')
        run_tool(['ffmpeg','-v','error','-nostdin','-y','-ss',f'{source_start:.6f}',
                  '-i',str(source),'-i',plan['paths']['audio_path'],'-filter_complex',video+';'+audio,
                  '-map','[v]','-map','[a]','-c:v','libx264','-threads','2','-crf','20',
                  '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t',f'{length:.6f}',
                  '-movflags','+faststart',str(output)],timeout=600,cwd=str(work))
    return output


def render_subtitle_still(config,start,output):
    """Render one timeline frame with the exact burn-in subtitle filter."""
    clips=config['clips']
    narration=config.get('narration') or {}
    subtitle_path=narration.get('subtitle_srt')
    if not subtitle_path or not Path(subtitle_path).is_file():
        raise InputError('Select an SRT file to preview subtitles')
    read_subtitles(subtitle_path)
    style=normalize_subtitle_style(narration.get('subtitle_style'))
    start=float(start)
    total=sum(float(clip['target_seconds']) for clip in clips)
    if not math.isfinite(start) or not 0<=start<total:
        raise InputError('Preview time must be within the current clip timeline')
    cursor=0.
    index=0
    for index,clip in enumerate(clips):
        if start<cursor+float(clip['target_seconds']):break
        cursor+=float(clip['target_seconds'])
    clip=clips[index];source=Path(clip['path'])
    metadata=json.loads(run_tool(['ffprobe','-v','error','-show_entries','format=duration',
                                  '-of','json',str(source)]).stdout)
    source_duration=float(metadata['format']['duration'])
    local=start-cursor
    source_time=min(local/float(clip['target_seconds'])*source_duration,max(0,source_duration-.04))
    first=json.loads(run_tool(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,sample_aspect_ratio','-of','json',clips[0]['path']]).stdout)['streams'][0]
    sar=first.get('sample_aspect_ratio','1:1').split(':')
    try:ratio=float(sar[0])/float(sar[1]) if len(sar)==2 and float(sar[1]) else 1
    except ValueError:ratio=1
    width=max(2,round(int(first['width'])*ratio/2)*2)
    height=max(2,round(int(first['height'])/2)*2)
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='subtitle-still-') as temporary:
        work=Path(temporary)
        write_positioned_ass(subtitle_path,work/'narration.ass',style,width,height)
        if style['font_path']:
            font=Path(style['font_path']).resolve()
            if not font.is_file() or font.suffix.lower() not in ('.ttf','.otf','.ttc'):
                raise InputError('Custom subtitle font must be an existing TTF, OTF, or TTC file')
            fonts=work/'fonts';fonts.mkdir()
            shutil.copyfile(font,fonts/font.name)
        fit=(f'scale=trunc(iw*sar/2)*2:ih,setsar=1,'
             f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
             f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,'
             f'setpts=PTS-STARTPTS+{start:.6f}/TB,'
             +subtitle_filter(style,fontsdir=bool(style['font_path']),filename='narration.ass'))
        run_tool(['ffmpeg','-v','error','-nostdin','-y','-ss',f'{source_time:.6f}',
            '-i',str(source),'-vf',fit,'-frames:v','1','-an','-threads','2',
            '-update','1',str(output)],timeout=120,cwd=str(work))
    return output
