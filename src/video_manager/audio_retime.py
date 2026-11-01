"""Retiming original audio to follow the rendered video frame map."""
from fractions import Fraction
from pathlib import Path
import tempfile

import numpy as np

from .errors import ToolError
from .tools import run_tool


SAMPLE_RATE=48000


def _resample_variable_speed(audio,positions,source_times,sample_rate):
    """Windowed-sinc resampling with a speed-dependent anti-alias cutoff."""
    radius=24
    source=np.pad(audio,((0,0),(radius,radius)),mode='constant')
    positions=np.asarray(positions,dtype=np.float64)+radius
    speed=np.gradient(np.asarray(source_times,dtype=np.float64))*sample_rate
    cutoff=np.minimum(1.0,1.0/np.maximum(np.abs(speed),1.0))
    output=np.zeros((audio.shape[0],len(positions)),dtype=np.float32)
    offsets=np.arange(-radius+1,radius+1,dtype=np.int64)
    for start in range(0,len(positions),2048):
        end=min(start+2048,len(positions))
        p=positions[start:end]
        center=np.floor(p).astype(np.int64)
        indexes=center[:,None]+offsets[None,:]
        distance=p[:,None]-center[:,None]-offsets[None,:]
        local_cutoff=cutoff[start:end,None]
        kernel=local_cutoff*np.sinc(local_cutoff*distance)*np.sinc(distance/radius)
        kernel[np.abs(distance)>=radius]=0
        kernel/=np.maximum(kernel.sum(axis=1,keepdims=True),1e-12)
        valid=(indexes>=radius)&(indexes<radius+audio.shape[1])
        kernel*=valid
        indexes=np.clip(indexes,0,source.shape[1]-1)
        for channel in range(audio.shape[0]):
            output[channel,start:end]=np.sum(source[channel,indexes]*kernel,axis=1).astype(np.float32)
    return output


def _extract_audio(clip,path):
    run_tool(['ffmpeg','-v','error','-nostdin','-y','-i',str(clip.path),'-map','0:a:0',
              '-vn','-af','asetpts=PTS-STARTPTS','-ar',str(SAMPLE_RATE),'-ac','2',
              '-c:a','pcm_f32le','-f','f32le',str(path)],timeout=600)
    samples=np.fromfile(path,dtype='<f4')
    if samples.size%2:raise ToolError(f'{clip.path.name}: extracted audio has an invalid sample count')
    audio=samples.reshape(-1,2).T
    offset=round(clip.audio_offset_seconds*SAMPLE_RATE)
    if offset>0:audio=np.pad(audio,((0,0),(offset,0)))
    elif offset<0:audio=audio[:,min(-offset,audio.shape[1]):]
    return audio


def render_audio(clips,frame_maps,frame_counts,fps,output_path,*,progress=None):
    """Map original audio through video frame maps without model inference.

    This uses varispeed resampling, so audio pitch changes with clip speed.
    """
    audio_clips=[clip for clip in clips if clip.has_audio]
    if not audio_clips:return dict(has_audio=False,mode='preserve',reason='no_source_audio',sample_rate=SAMPLE_RATE)
    fps=Fraction(fps)
    total_frames=sum(frame_counts)
    total_samples=round(total_frames*SAMPLE_RATE/float(fps))
    written=0
    with tempfile.TemporaryDirectory(prefix='video-manager-audio-') as temporary:
        raw=Path(temporary)/'source.f32le'
        with Path(output_path).open('wb') as destination:
            for ci,(clip,source_map,frame_count) in enumerate(zip(clips,frame_maps,frame_counts),1):
                first_sample=round(sum(frame_counts[:ci-1])*SAMPLE_RATE/float(fps))
                end_sample=round(sum(frame_counts[:ci])*SAMPLE_RATE/float(fps))
                count=end_sample-first_sample
                if clip.has_audio:
                    if progress:progress(f'Reading original audio from {clip.id}',ci-1,len(clips))
                    source=_extract_audio(clip,raw)
                    audio=source if source.shape[1] else np.zeros((2,1),dtype=np.float32)
                else:audio=np.zeros((2,1),dtype=np.float32)
                frame_times=np.arange(len(source_map),dtype=np.float64)/float(fps)
                output_times=np.arange(count,dtype=np.float64)/SAMPLE_RATE
                source_times=np.interp(output_times,frame_times,np.asarray(source_map,dtype=np.float64))
                segment=_resample_variable_speed(audio,source_times*SAMPLE_RATE,source_times,SAMPLE_RATE)
                destination.write(np.ascontiguousarray(segment.T,dtype='<f4').tobytes())
                written+=count
                if progress:progress(f'Retimed original audio · {clip.id}',ci,len(clips))
        if written!=total_samples:raise ToolError('Retimed audio duration does not match the rendered frame budget')
    return dict(has_audio=True,mode='preserve',sample_rate=SAMPLE_RATE,channels=2,samples=written,
                source_audio_clips=sum(clip.has_audio for clip in clips),retained_audio='original_mix',
                time_map='video frame map; varispeed resampling')


def mux_audio(video_path,audio_path,output_path,fps,frame_count):
    duration=frame_count/float(Fraction(fps))
    run_tool(['ffmpeg','-v','error','-nostdin','-y','-i',str(video_path),
              '-f','f32le','-ar',str(SAMPLE_RATE),'-ac','2','-i',str(audio_path),
              '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
              '-t',f'{duration:.9f}','-movflags','+faststart',str(output_path)],timeout=600)
    return Path(output_path)
