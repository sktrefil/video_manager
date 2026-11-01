"""Conservative measured-motion time warps; no pixel synthesis or intent claim."""
import numpy as np


def _score(source_times, speed_times, speeds, fps):
    # A sample describes the interval ending at its timestamp (not a point speed).
    distance=np.r_[0.,np.cumsum(speeds[1:]*np.diff(speed_times))]
    positions=np.interp(source_times,speed_times,distance)
    velocity=np.diff(positions)*fps
    acceleration=np.diff(velocity)*fps
    return dict(acceleration_variance=float(np.var(acceleration)),
                movement_extent=float(positions[-1]-positions[0]),
                repeat_fraction=float(np.mean(np.diff(positions)<.1)))


def optimize_region(mapping, region):
    """Return absolute source-time knots. Caller alone decides whether to apply.

All candidates preserve region endpoints. Frame-quantized objective is evaluated
under the actual output time map, and unchanged/no-improvement schedules reject.
The objective is a tracked-distance proxy, not a claim of visual quality.
"""
    def reject(reason,**extra): return dict(accepted=False,reason=reason,knots=[],**extra)
    start=float(region['start_seconds']); end=float(region['end_seconds'])
    if start<min(mapping.protect,mapping.source_end)-1e-10: return reject('protected_interval_priority')
    if end<=start or end>mapping.source_end+1e-9: return reject('invalid_region_bounds')
    if region.get('fully_static'): return reject('fully_static_no_new_motion')
    # Identical frames cannot establish whether a pause was intentional. Selection
    # is not semantic confirmation; this release keeps every hold diagnostic-only.
    if 'repeat_or_hold' in region.get('kinds',[]) or region.get('ambiguous_hold_overlap'):
        return reject('ambiguous_hold_intent')
    if region.get('confidence',0)<.6: return reject('low_tracking_confidence')
    samples=region.get('motion_samples',[])
    if len(samples)<6: return reject('insufficient_motion_samples')
    times=np.array([s['seconds'] for s in samples],dtype=float)
    speeds=np.array([s['speed'] for s in samples],dtype=float)
    if (not np.all(np.isfinite(times)) or not np.all(np.isfinite(speeds)) or
        np.any(np.diff(times)<=0) or np.any(speeds<0)):
        return reject('invalid_motion_samples')
    if any(s.get('confidence',0)<.6 for s in samples): return reject('low_tracking_confidence')
    if float(np.max(speeds))<.5: return reject('insufficient_motion')
    if float(np.std(speeds))/(float(np.mean(speeds))+.1)<.12: return reject('steady_motion_no_correction')
    # These timestamps must be the actual source frames, not arbitrary analysis knots.
    frame_times=np.array(region.get('source_frame_times',times),dtype=float)
    if len(frame_times)<2 or np.any(np.diff(frame_times)<=0) or not np.all(np.isfinite(frame_times)):
        return reject('invalid_source_frame_times')
    context=region.get('context_motion_samples',[])
    if len(context)!=len(frame_times)-1: return reject('missing_full_motion_context')
    context_times=np.array([s['seconds'] for s in context],dtype=float)
    context_speeds=np.array([s['speed'] for s in context],dtype=float)
    if (not np.all(np.isfinite(context_times)) or not np.all(np.isfinite(context_speeds)) or
        np.any(context_speeds<0) or not np.allclose(context_times,frame_times[1:],atol=1e-9,rtol=0)):
        return reject('invalid_full_motion_context')
    if any(s.get('confidence',0)<.6 for s in context): return reject('unreliable_full_motion_context')
    def quantize(values):
        right=np.clip(np.searchsorted(frame_times,values),1,len(frame_times)-1)
        left=right-1
        return frame_times[np.where(abs(frame_times[left]-values)<=abs(frame_times[right]-values),left,right)]
    out=np.arange(mapping.count)/float(mapping.fps)
    base=np.array([mapping.source_time(float(t)) for t in out])
    selected=np.flatnonzero((base>=start)&(base<=end))
    if len(selected)<6: return reject('insufficient_output_samples')
    # Include adjacent samples to penalize entry/exit acceleration.
    lo=max(0,selected[0]-2); hi=min(len(base),selected[-1]+3)
    # Full source context is essential: clipping distance to region bounds makes
    # false zero-speed shoulders, which can inflate the apparent local gain.
    speed_times=np.r_[frame_times[0],context_times]
    speed_values=np.r_[context_speeds[0],context_speeds]
    original=quantize(base)
    before=_score(original,speed_times,speed_values,float(mapping.fps))
    local_before=_score(original[lo:hi],speed_times,speed_values,float(mapping.fps))
    if before['acceleration_variance']<1e-8: return reject('steady_motion_no_correction')
    grid=np.linspace(start,end,33)
    measured=np.interp(grid,speed_times,speed_values)
    # A speed floor prevents a hold being erased, and limits sensitivity to noise.
    floor=max(.5,float(np.median(speeds[speeds>0]))*.25)
    regularized=np.maximum(measured,floor)
    distance=np.r_[0.,np.cumsum((regularized[:-1]+regularized[1:])*.5*np.diff(grid))]
    desired=np.interp(np.linspace(0,distance[-1],len(grid)),distance,grid)
    u=(grid-start)/(end-start)
    envelope=np.sin(np.pi*u)**2
    displacement=envelope*(desired-grid)
    displacement[:2]=0.;displacement[-2:]=0.
    delta_slopes=np.diff(displacement)/np.diff(grid)
    maximum_derivative=mapping.max_speed/mapping.speed_bound()
    upper=1.
    for delta in delta_slopes:
        if delta>0: upper=min(upper,(maximum_derivative-1)/delta)
        elif delta<0: upper=min(upper,.899999999/-delta)
    if upper<=0: return reject('composed_speed_limit')
    sample_displacement=np.zeros_like(base)
    sample_displacement[selected]=np.interp(base[selected],grid,displacement)
    # Nearest-frame schedules are piecewise constant in strength. Search every
    # source-frame midpoint crossing and intervening interval instead of relying
    # on a coarse hand-picked grid that can miss the actual discrete optimum.
    midpoints=(frame_times[:-1]+frame_times[1:])*.5
    breaks={0.,float(upper)}
    for value,delta in zip(base,sample_displacement):
        if abs(delta)<1e-12: continue
        low,high=sorted((value,value+upper*delta))
        for midpoint in midpoints[np.searchsorted(midpoints,low):np.searchsorted(midpoints,high,side='right')]:
            strength=float((midpoint-value)/delta)
            if 0<strength<upper: breaks.add(strength)
            if len(breaks)>4096: return reject('optimization_budget_exceeded')
    breaks=sorted(breaks)
    # Mid-interval representatives avoid floating-point-sensitive tie schedules.
    strengths=[(left+right)*.5 for left,right in zip(breaks,breaks[1:]) if right-left>1e-12]
    best=None; evaluated=[]
    for strength in strengths:
        values=grid+strength*displacement
        slopes=np.diff(values)/np.diff(grid)
        if min(slopes)<=.1 or mapping.speed_bound()*max(1.,float(max(slopes)))>mapping.max_speed+1e-9:
            continue
        knots=np.column_stack((grid,values)).tolist()
        warped=base+strength*sample_displacement
        final=quantize(warped)
        if np.array_equal(final,original) or np.any(np.diff(warped)<0): continue
        after=_score(final,speed_times,speed_values,float(mapping.fps))
        local_after=_score(final[lo:hi],speed_times,speed_values,float(mapping.fps))
        gain=1-after['acceleration_variance']/before['acceleration_variance']
        evaluated.append(dict(strength=strength,gain=float(gain),after=after))
        if gain<.10 or after['movement_extent']<.95*before['movement_extent']: continue
        if local_after['acceleration_variance']>local_before['acceleration_variance']+1e-9: continue
        if after['repeat_fraction']>before['repeat_fraction']+.02+1e-9: continue
        if best is None or gain>best['metrics']['acceleration_variance_reduction']:
            best=dict(accepted=True,reason='candidate_requires_visual_review',knots=knots,strength=strength,
                metrics=dict(before=before,after=after,acceleration_variance_reduction=gain,
                             local_before=local_before,local_after=local_after,
                             changed_source_selections=int(np.count_nonzero(final!=original)),
                             objective='whole_clip_tracked_distance_proxy_quantized_source_frames'))
    return best or reject('no_verified_improvement',metrics=dict(before=before,evaluated=evaluated))
