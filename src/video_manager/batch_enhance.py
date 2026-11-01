"""Sequential folder processing for the standalone video enhancement app."""
from __future__ import annotations

from pathlib import Path
import json
import tempfile

from .errors import InputError
from .probe import probe
from .render import frame_schedule, render_clips
from .tools import run_tool


VIDEO_EXTENSIONS={'.mp4','.mov','.mkv','.avi','.m4v','.webm'}
OUTPUT_FOLDER='video_manager_output'
ENGINE_REVISION='watermark-inpaint-v1'


def _identity(path):
    stat=Path(path).stat()
    return dict(path=str(Path(path).resolve()),size=stat.st_size,mtime_ns=stat.st_mtime_ns)


def _write_json(path,payload):
    path=Path(path)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,suffix='.json',delete=False) as stream:
        temporary=Path(stream.name)
        json.dump(payload,stream,ensure_ascii=False,indent=2)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def is_completed(source,destination,options):
    """Only reuse results made with this source, algorithm and exact settings."""
    from .enhancements import normalize_enhancements
    try:
        record=json.loads(Path(str(destination)+'.json').read_text(encoding='utf-8'))
        return (record.get('engine')==ENGINE_REVISION and record.get('source')==_identity(source)
                and record.get('output')==_identity(destination)
                and record.get('options')==normalize_enhancements(options))
    except (OSError,ValueError,TypeError,AttributeError):
        return False


def load_regions(destination):
    path=Path(str(destination)+'.regions.json')
    if not path.exists():return None
    from .watermark_crop import validate_regions
    return validate_regions(json.loads(path.read_text(encoding='utf-8')))


def save_regions(destination,regions):
    from .watermark_crop import validate_regions
    Path(destination).parent.mkdir(parents=True,exist_ok=True)
    _write_json(str(destination)+'.regions.json',validate_regions(regions))


def discover_videos(folder: Path) -> list[Path]:
    folder=Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise InputError(f'Video folder does not exist: {folder}')
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS),
                  key=lambda p:p.name.casefold())


def output_path(source: Path, folder: Path) -> Path:
    return Path(folder)/OUTPUT_FOLDER/f'{source.stem}_enhanced_{source.suffix[1:].lower()}.mp4'


def process_video(source: Path, destination: Path, options: dict, *, interpolate: bool=False,
                  progress=None) -> Path:
    """Render one source through the shared effect pipeline and keep its audio."""
    from .enhancements import normalize_enhancements
    options=normalize_enhancements(options)
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():raise InputError(f'Input video does not exist: {source}')
    if source==destination:raise InputError('Output must not overwrite the source video')
    if not any(options[key]['enabled'] for key in ('watermark','stabilization','interpolation')):
        raise InputError('Select at least one video effect')
    destination.parent.mkdir(parents=True,exist_ok=True)
    source_identity=_identity(source)
    clip=probe(source,source.stem)
    interpolate=options['interpolation']['enabled']
    fps=clip.fps*2 if interpolate else clip.fps
    schedule=frame_schedule(clip,fps)
    times=[frame['source_seconds'] for frame in clip.frames]
    source_times=[min(times[-1],i/float(fps)) for i in range(len(schedule))]
    source_times[-1]=times[-1]
    if not interpolate:
        source_times=[times[index] for index in schedule]
    with tempfile.TemporaryDirectory(prefix='.video-enhance-',dir=destination.parent) as temporary:
        work=Path(temporary)
        rendered=work/'rendered.mp4'
        result=render_clips([clip],work,schedules=[schedule],prefix='rendered',output_fps=fps,
                     enhancements=options,source_times=[source_times],protects=[0],include_diagnostic=False)
        if progress:progress('Adding original audio')
        muxed=work/'muxed.mp4'
        run_tool(['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(rendered),
                  '-i',str(source),'-map','0:v:0','-map','1:a?','-c:v','copy','-c:a','aac',
                  '-b:a','192k','-t',f'{len(schedule)/float(fps):.9f}','-movflags','+faststart',str(muxed)],
                 timeout=max(600,clip.duration*30))
        if not muxed.is_file() or muxed.stat().st_size==0:
            raise InputError(f'FFmpeg did not produce output for {source.name}')
        if _identity(source)!=source_identity:
            raise InputError('처리 중 원본 파일이 변경되어 결과 저장을 중단했습니다.')
        muxed.replace(destination)
        _write_json(str(destination)+'.json',dict(engine=ENGINE_REVISION,source=source_identity,
            output=_identity(destination),options=options,effects=result.get('enhancements',[])))
    return destination
