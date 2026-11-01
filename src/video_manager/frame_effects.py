"""Bounded two-frame rendering: source stabilization then optional interpolation."""
from bisect import bisect_left
from collections import Counter

import numpy as np

from .errors import InputError,ToolError
from .enhancements import normalize_enhancements


def interpolation_guard(pair,median_dt):
    if pair['cut'] or pair['abstain_reason'] or pair['confidence']<.6:
        return pair['abstain_reason'] or 'low_tracking_confidence'
    if pair['dt']>2.01*median_dt:return 'source_time_gap'
    return None


class FrameEffects:
    def __init__(self,clip,width,height,options,protect=0):
        self.clip=clip;self.width=width;self.height=height;self.protect=protect
        self.options=normalize_enhancements(options)
        self.transforms=None;self.backend=None;self.pairs=[]
        self.counts=Counter();self.interpolated=0;self.transformed=0
        self.mark_mask=None;self.mark_removed=0;self.crop_plan=None
        self.audit=dict(options=self.options,order=['source_mark_removal','source_stabilization','target_time_interpolation'],
                        stabilization=dict(applied=False,reason='disabled'))
        if self.options['watermark']['enabled']:
            watermark=self.options['watermark']
            if watermark.get('profile')=='both':
                self.audit['order']=['source_stabilization','target_time_interpolation','watermark_minimal_crop']
            else:
                from .watermark import mark_mask
                self.mark_mask,rectangle=mark_mask(clip,width,height,watermark)
                method='selected_regions_opencv_ns_inpaint' if watermark.get('regions') is not None else 'four_point_mask_opencv_ns_inpaint'
                self.audit['watermark']=dict(applied=True,rectangle=rectangle,method=method)
        else:self.audit['watermark']=dict(applied=False,reason='disabled')
        if self.options['stabilization']['enabled']:
            from .stabilization import plan_stabilization
            s=self.options['stabilization']
            plan=plan_stabilization(clip,output_size=(width,height),crop_budget=s['max_crop_fraction'],
                smooth_seconds=s['smoothing_seconds'],protect_seconds=protect,strength=s['strength'])
            self.transforms=plan['transforms'];self.audit['stabilization']=plan['audit']
        if self.options['watermark']['enabled'] and self.options['watermark'].get('profile')=='both':
            from .watermark_crop import plan_crop
            self.crop_plan=plan_crop(width,height,self.options['watermark'].get('regions'),
                                     transforms=self.transforms,clip=clip)
            self.audit['watermark']=dict(applied=self.crop_plan['zoom']>1,**self.crop_plan)
        if self.options['interpolation']['enabled']:
            from .motion_analysis import analyze_motion,ANALYSIS_VERSION
            from .interpolation import create_backend
            self.backend=create_backend(self.options['interpolation']['backend'])
            self.pairs=analyze_motion(clip)['pairs']
            self.audit['guard_analysis_version']=ANALYSIS_VERSION

    def frames(self,schedule,source_times,fps):
        from .render import decode_frames
        from .stabilization import apply_transform
        times=[frame['source_seconds'] for frame in self.clip.frames]
        if len(source_times)!=len(schedule) or any(not np.isfinite(t) for t in source_times):
            raise InputError('Enhancement timestamps must match the output frame budget')
        if any(b<a for a,b in zip(source_times,source_times[1:])):
            raise InputError('Enhancement source timestamps must be monotonic')
        decoder=decode_frames(self.clip,self.width,self.height)
        current=-1;raw={};converted={}
        def obtain(index):
            nonlocal current
            while current<index:
                try:data=next(decoder)
                except StopIteration as exc:raise ToolError('Insufficient decoded frames for enhancement') from exc
                current+=1
                source_frame=np.frombuffer(data,np.uint8).reshape(self.height,self.width,3)
                if self.mark_mask is not None:
                    from .watermark import remove_mark
                    source_frame=remove_mark(source_frame,self.mark_mask)
                    self.mark_removed+=1
                raw[current]=source_frame
                for old in list(raw):
                    if old<current-1:raw.pop(old);converted.pop(old,None)
            if index not in raw:raise ToolError('Enhancement schedule exceeded the frame buffer')
            if index not in converted:
                frame=raw[index]
                if self.transforms is not None:frame=apply_transform(frame,self.transforms[index])
                converted[index]=frame
            return converted[index]
        try:
            for output_index,(nearest,value) in enumerate(zip(schedule,source_times)):
                value=min(times[-1],max(times[0],float(value)))
                right=min(len(times)-1,bisect_left(times,value));left=max(0,right-1)
                alpha=(value-times[left])/(times[right]-times[left]) if right>left else 0.
                reason='disabled';applied=False;details={}
                eligible=self.backend is not None
                if min(self.width,self.height)<16:eligible=False;reason='unsupported_frame_dimensions'
                elif output_index in (0,len(schedule)-1):eligible=False;reason='endpoint_preserved'
                elif value<=self.protect+1e-9 or (self.protect>0 and times[left]<self.protect):
                    eligible=False;reason='protected_interval_priority'
                elif right==left or alpha<1e-8 or alpha>1-1e-8:
                    eligible=False;reason='source_timestamp'
                if eligible:
                    pair=self.pairs[right-1]
                    guard=interpolation_guard(pair,float(np.median(np.diff(times))))
                    if guard:eligible=False;reason=guard
                if eligible:
                    a=obtain(left);b=obtain(right)
                    composed={}
                    if self.transforms is not None:
                        composed=dict(source_frames=(raw[left],raw[right]),
                                      source_transforms=(self.transforms[left],self.transforms[right]))
                    frame,details=self.backend.synthesize(a,b,float(alpha),**composed)
                    applied=details['applied'];reason=details['reason']
                    if not applied:frame=obtain(nearest)
                else:frame=obtain(nearest)
                if self.crop_plan is not None:
                    from .watermark_crop import apply_crop
                    frame=apply_crop(frame,self.crop_plan)
                self.counts[reason]+=1;self.interpolated+=int(applied)
                indices=[left,right] if applied else [nearest]
                spatial=[]
                if self.transforms is not None:
                    spatial=[dict(source_frame=i,matrix=self.transforms[i]) for i in indices]
                    self.transformed+=int(any(not np.allclose(entry['matrix'],[[1,0,0],[0,1,0]],atol=1e-10) for entry in spatial))
                yield nearest,frame.tobytes(),dict(requested_source_seconds=value,
                    interpolation=dict(applied=applied,reason=reason,left_frame=left,right_frame=right,
                        left_seconds=times[left],right_seconds=times[right],alpha=float(alpha),details=details),
                    spatial_transforms=spatial)
            # Consume EOF so FFmpeg's exit code and any surplus/truncated frames
            # are checked before a completed render can be published.
            for _ in decoder:current+=1
            if current+1!=len(times):raise ToolError('Decoded enhancement frame count differs from source metadata')
        finally:decoder.close()

    def summary(self):
        return dict(self.audit,interpolated_output_frames=self.interpolated,
                    transformed_output_frames=self.transformed,interpolation_reasons=dict(self.counts),
                    watermark_removed_source_frames=self.mark_removed)
