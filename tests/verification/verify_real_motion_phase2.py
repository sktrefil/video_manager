"""Audit completed real preview artifacts without rerendering their effects."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from video_manager.probe import probe
from video_manager.render import decode_frames


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def main():
    root=Path(sys.argv[1]);read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    provenance=read(root/'provenance.json');results=read(root/'results.json')
    assert provenance['code_unchanged'] and provenance['originals_unchanged']
    assert provenance['code_before']==provenance['code_after']
    assert all(sha(path)==value for path,value in provenance['code_after'].items())
    assert len(results)==4
    verified=[]
    for result in results:
        source=Path(result['source']);assert sha(source)==result['source_sha256']
        native=probe(source,source.stem);folder=root/source.stem;fps=float(native.fps)
        width,height=result['preview_size'];assert width==640
        control_path=folder/result['same_codec_control']['file']
        assert sha(control_path)==result['same_codec_control']['sha256']
        control=list(decode_frames(probe(control_path,'control'),width,height))
        variants={}
        for name,entry in result['variants'].items():
            video_path=folder/(name+'.mp4');mapping_path=folder/(name+'_mapping.json')
            assert sha(video_path)==entry['video_sha256'] and sha(mapping_path)==entry['mapping_sha256']
            video=probe(video_path,name);mapping=read(mapping_path)['mapping']
            assert len(video.frames)==len(mapping)==entry['frame_count']
            assert abs(video.duration-result['target_seconds'])<=1/fps
            assert mapping[0]['source_frame']==0 and mapping[-1]['source_frame']==len(native.frames)-1
            indices=[row['source_frame'] for row in mapping];assert indices==sorted(indices)
            applied=spatial=0
            for index,row in enumerate(mapping):
                interpolation=row.get('interpolation',{});transforms=row.get('spatial_transforms',[])
                transformed=any(not np.allclose(t['matrix'],[[1,0,0],[0,1,0]],atol=1e-9) for t in transforms)
                applied+=int(interpolation.get('applied',False));spatial+=int(transformed)
                if interpolation.get('applied'):
                    assert interpolation['right_frame']-interpolation['left_frame']==1
                    assert 0<interpolation['alpha']<1
                if index in (0,len(mapping)-1) or row.get('requested_source_seconds',row['source_seconds'])<=1:
                    assert not interpolation.get('applied') and not transformed
            item=dict(frames=len(video.frames),duration=video.duration,interpolated=applied,spatial=spatial)
            if name!='baseline':
                actual=list(decode_frames(video,width,height));changed=sum(a!=b for a,b in zip(actual,control,strict=True))
                assert changed==entry['decoded_comparison']['decoded_changed_frames']
                claimed=entry['preencoding_attribution']
                assert applied==claimed['interpolated_output_frames'] and spatial==claimed['spatial_output_frames']
                assert claimed['changed_output_frames']==len(claimed['changed_frame_indices'])
                item.update(independently_decoded_changed_frames=changed,
                            reported_preencode_changed_frames=claimed['changed_output_frames'])
            variants[name]=item
        assert sha(Path(result['comparison']))==result['comparison_sha256']
        montage=probe(Path(result['comparison']),'comparison');assert len(montage.frames)==len(control)
        verified.append(dict(source=str(source),preview_size=[width,height],variants=variants))
        print(source.name,variants,flush=True)
    report=dict(technical_artifact_audit_passed=True,preview_only=True,rows=verified,
                preencode_note='Producer counts cross-checked against frame audit; effects were not independently rerendered.',
                real_visual_quality='not approved',product_hashes=provenance['code_after'])
    (root/'independent_verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':main()
