"""Verify a real four-video batch; keep originals read-only and write review artifacts."""
import argparse
import hashlib
from html import escape
from itertools import zip_longest
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import quote

import numpy as np
from PIL import Image, ImageDraw

from video_manager.batch_enhance import process_video, is_completed, discover_videos
from video_manager.probe import probe
from video_manager.render import decode_frames
from video_manager.tools import run_tool
from video_manager.watermark_crop import apply_crop


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def audio_samples(path):
    result=subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-map','0:a:0',
        '-ac','1','-ar','16000','-f','f32le','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    return np.frombuffer(result.stdout,dtype='<f4')


def verify(source,destination,number):
    started=time.monotonic();original_hash=digest(source)
    before=probe(source,'source');settings={'watermark':{'enabled':True,'profile':'both'}}
    process_video(source,destination,settings)
    after=probe(destination,'result')
    run_tool(['ffmpeg','-v','error','-nostdin','-i',str(destination),'-f','null','-'],timeout=180)
    record=json.loads(Path(str(destination)+'.json').read_text(encoding='utf-8'))
    plan=record['effects'][0]['watermark']
    assert (before.width,before.height,before.fps,len(before.frames))==(after.width,after.height,after.fps,len(after.frames))
    assert before.has_audio==after.has_audio
    assert digest(source)==original_hash
    assert is_completed(source,destination,settings)
    sampled={round(t*(len(before.frames)-1)) for t in (0,.25,.5,.75,1)}
    comparisons=[];errors=[];sample_frames=[]
    originals=decode_frames(before,before.width,before.height)
    results=decode_frames(after,after.width,after.height)
    try:
        for index,(a,b) in enumerate(zip_longest(originals,results)):
            assert a is not None and b is not None,'Frame count mismatch'
            original=np.frombuffer(a,np.uint8).reshape(before.height,before.width,3)
            actual=np.frombuffer(b,np.uint8).reshape(after.height,after.width,3)
            expected=apply_crop(original,plan)
            errors.append(float(np.mean(np.abs(expected.astype(np.int16)-actual.astype(np.int16)))))
            if index in sampled:
                left=Image.fromarray(original);draw=ImageDraw.Draw(left)
                for box in plan['excluded_boxes']:draw.rectangle(box,outline='#ff6040',width=3)
                x,y,w,h=plan['rect'];draw.rectangle((x,y,x+w-1,y+h-1),outline='#30ee80',width=3)
                comparisons.append((left,Image.fromarray(actual),index/float(before.fps)))
                sample_frames.append(index)
    finally:originals.close();results.close()
    assert max(errors)<8,'Unexpected image deviation from the intended crop'
    sheet=Image.new('RGB',(1280,len(comparisons)*404),'#202124');draw=ImageDraw.Draw(sheet)
    for row,(left,right,seconds) in enumerate(comparisons):
        draw.text((10,row*404+6),f'{number:02} {source.name[:55]} | ORIGINAL {seconds:.3f}s | red=logos green=retained',fill='white')
        draw.text((650,row*404+6),'PROCESSED',fill='white')
        for column,image in enumerate((left,right)):
            image.thumbnail((640,370));sheet.paste(image,(column*640,row*404+28))
    comparison=destination.parent/f'{number:02}-comparison.jpg';sheet.save(comparison,quality=94)
    audio={}
    if before.has_audio:
        a,b=audio_samples(source),audio_samples(destination);count=min(len(a),len(b))
        correlation=float(np.corrcoef(a[:count],b[:count])[0,1]) if np.std(a[:count])>1e-8 and np.std(b[:count])>1e-8 else None
        audio=dict(source_seconds=len(a)/16000,result_seconds=len(b)/16000,correlation=correlation,
                   source_rms=float(np.sqrt(np.mean(a*a))),result_rms=float(np.sqrt(np.mean(b*b))))
        assert abs(len(a)-len(b))/16000<.15,'Audio length changed'
        if correlation is not None:assert correlation>.95,'Audio content changed unexpectedly'
    return dict(source=str(source),result=str(destination),source_sha256=original_hash,source_unchanged=True,
        resolution=[after.width,after.height],fps=str(after.fps),frames=len(after.frames),
        source_seconds=before.duration,result_seconds=after.duration,decode_ok=True,completion_receipt_ok=True,
        watermark_crop=plan,mean_pixel_error=float(np.mean(errors)),max_frame_pixel_error=max(errors),
        sampled_frames=sample_frames,comparison=str(comparison),audio=audio,elapsed_seconds=time.monotonic()-started,
        visual_review='pending',scope='watermark only; stabilization and interpolation disabled')


def write_report(records,output):
    rows=[];players=[]
    for index,r in enumerate(records,1):
        name=escape(Path(r['source']).name);video=quote(Path(r['result']).name)
        if r['automated_checks']!='passed':
            rows.append(f'<tr><td>{name}</td><td colspan="4">실패: {escape(r.get("error",""))}</td></tr>');continue
        visual=r.get('visual_review');reviewed=isinstance(visual,dict) and visual.get('watermark_visible') is False
        status='자동 검사 통과 / 비교 장면 로고 없음' if reviewed else '자동 검사 통과 / 육안 확인 대기'
        comparison=quote(Path(r['comparison']).name)
        kept=100*r['watermark_crop']['retained_area_fraction'];w,h=r['resolution']
        rows.append(f'<tr><td>{name}</td><td>{status}</td><td>{r["result_seconds"]:.3f}초 · {r["fps"]}fps · '
                    f'{r["frames"]}프레임</td><td>{w}×{h}</td><td>{kept:.1f}%</td></tr>')
        players.append(f'<section><h2>{index:02} · {name}</h2><video controls preload="metadata" src="{video}"></video>'
                       f'<p><a href="{video}">결과 영상 열기</a> · <a href="{comparison}">원본/결과 5장면 비교</a></p>'
                       f'<details><summary>비교 이미지 펼치기</summary><img src="{comparison}" alt="원본과 결과 비교"></details></section>')
    html='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>워터마크 4개 실영상 검증</title><style>
body{max-width:1200px;margin:36px auto;padding:0 24px;font:16px/1.6 "Malgun Gothic",sans-serif;background:#151a21;color:#e5edf6}
h1{font-size:28px}h2{font-size:18px;overflow-wrap:anywhere}a{color:#83c7ff}table{border-collapse:collapse;width:100%;font-size:14px}
td,th{padding:12px;border-bottom:1px solid #394352;text-align:left;overflow-wrap:anywhere}td:first-child{max-width:330px}
section{margin-top:32px;padding:20px;background:#222a35;border-radius:12px}video{width:100%;max-height:580px;background:black}
img{width:100%;height:auto}summary{cursor:pointer}small{color:#b6c2d2}</style><body>
<h1>워터마크 4개 실영상 검증</h1>
<p>기본 Hailuo·Gemini 영역 동시 처리. 워터마크 크롭만 켜고 흔들림 보정·보간은 껐습니다.</p>
<p>전 프레임을 디코딩해 예상 크롭과 비교하고, 해상도·FPS·길이·오디오·완료 기록 및 원본 SHA-256 보존을 확인했습니다.
육안 검토는 각 영상의 시작·25%·50%·75%·끝 5장면입니다. 전체 프레임을 사람이 검토한 것은 아닙니다.</p>
<p>이 결과는 로고를 포함한 영역을 화면 밖으로 자르는 방식입니다. 원본 화면 면적 약 23.4%가 잘리며 약 1.143배 확대됩니다.</p>
<table><thead><tr><th>파일</th><th>검증</th><th>시간/프레임</th><th>해상도</th><th>유지 면적</th></tr></thead><tbody>'''
    html+=''.join(rows)+'</tbody></table>'+''.join(players)
    html+='<p><a href="verification.json">상세 검증 기록(JSON)</a></p></body></html>'
    (output/'review.html').write_text(html,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    files=discover_videos(args.folder)
    if len(files)!=4:raise ValueError(f'Expected four videos, found {len(files)}')
    records=[]
    for number,source in enumerate(files,1):
        print(f'[{number}/4] Processing {source.name}',flush=True)
        destination=args.output/f'{number:02}_{source.stem}_enhanced.mp4'
        try:
            record=verify(source,destination,number);record['automated_checks']='passed'
        except Exception as exc:
            record=dict(source=str(source),result=str(destination),automated_checks='failed',error=str(exc))
        records.append(record)
        (args.output/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(record,ensure_ascii=True),flush=True)
    write_report(records,args.output)
    return int(any(r['automated_checks']!='passed' for r in records))


if __name__=='__main__':raise SystemExit(main())
