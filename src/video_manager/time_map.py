"""Protected smooth retiming and jointly allocated CFR frame budgets."""
from bisect import bisect_left
from dataclasses import dataclass, field
from fractions import Fraction
import math

from .errors import InputError


def number(value, label, *, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)) or not math.isfinite(value):
        raise InputError(f'{label} must be a finite number')
    value = float(value)
    if value < minimum or (positive and value == minimum):
        raise InputError(f'{label} must be {">" if positive else ">="} {minimum}')
    return value


def allocate_frames(targets, fps):
    """Largest-remainder allocation keeps total and individual error <= one frame."""
    if not targets:
        raise InputError('At least one target duration is required')
    exact = [Fraction(str(number(t, 'target_seconds', positive=True))) * fps for t in targets]
    counts = [int(x) for x in exact]
    total = round(sum(exact))
    remaining = total-sum(counts)
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i]-counts[i]), i))
    for index in order[:remaining]:
        counts[index] += 1
    if any(n < 1 for n in counts):
        raise InputError('Each target must receive at least one output frame')
    return counts


@dataclass
class TimeMap:
    source_end: float
    output_end: float
    protect: float
    ramp: float
    peak: float
    compressed: bool
    count: int
    fps: Fraction
    max_speed: float
    source_warps: list = field(default_factory=list)
    region_warps: list = field(default_factory=list)

    def base_time(self, t):
        if not self.compressed:
            return min(t, self.source_end)
        if t <= self.protect:
            return t
        x = min(t, self.output_end)-self.protect
        if x < self.ramp:
            u = x/self.ramp
            extra = self.ramp*(u**3-0.5*u**4)
        else:
            extra = x-self.ramp/2
        return min(self.source_end, t+(self.peak-1)*extra)

    def base_speed(self, t):
        if not self.compressed or t <= self.protect:
            return 1.0
        u = min(1.0, (t-self.protect)/self.ramp)
        return 1+(self.peak-1)*(3*u*u-2*u*u*u)

    def source_time(self, t):
        value = self.base_time(t)
        for side, width, alpha in self.source_warps:
            start = 0 if side == 'head' else self.source_end-width
            if start <= value <= start+width:
                u = (value-start)/width
                q = u+alpha*u*(1-u)**2 if side == 'head' else u+alpha*u*u*(u-1)
                value = start+width*q
        for start,end,kind,amount in self.region_warps:
            if start<=value<=end:
                u=(value-start)/(end-start)
                q=(u-amount*math.sin(2*math.pi*u)*math.sin(math.pi*u)**2/(2*math.pi)
                   if kind=='hold' else u+amount*u*u*(1-u)**2)
                value=start+(end-start)*q
        return value

    def speed_bound(self):
        return (self.peak * math.prod(1+abs(w[2]) for w in self.source_warps)
                * math.prod(1+(2 if kind=='hold' else .25)*abs(amount)
                            for _,_,kind,amount in self.region_warps))

    def describe(self):
        return dict(compressed=self.compressed, protect_seconds=self.protect,
                    ramp_seconds=self.ramp, peak_speed=self.peak, max_speed=self.max_speed,
                    conservative_composed_speed_bound=self.speed_bound(),
                    source_last_display_seconds=self.source_end, output_last_display_seconds=self.output_end,
                    output_frames=self.count, internal_region_warps=[dict(start=s,end=e,kind=k,amount=a) for s,e,k,a in self.region_warps], source_warps=[dict(side=s,width=w,alpha=a) for s,w,a in self.source_warps])


def build_map(clip, target, protect, max_speed, ramp, count, fps, *, enabled=True):
    target = number(target, 'target_seconds', positive=True)
    protect = number(protect, 'protect_seconds')
    max_speed = number(max_speed, 'max_speed', minimum=1)
    ramp = number(ramp, 'ramp_seconds', positive=True)
    tolerance = float(1/fps)
    if protect > clip.duration+1e-9:
        raise InputError(f'{clip.id}: protection exceeds source duration')
    if target > clip.duration+tolerance:
        raise InputError(f'{clip.id}: duration extension is not supported')
    compressed = target < clip.duration-tolerance
    if not enabled and compressed:
        raise InputError(f'{clip.id}: disabled correction conflicts with target duration')
    if len(clip.frames)>1 and count<2:
        raise InputError(f'{clip.id}: at least two frames are required to preserve endpoints')
    source_end = clip.frames[-1]['source_seconds']
    output_end = (count-1)/float(fps)
    if not compressed:
        return TimeMap(source_end, output_end, protect, ramp, 1.0, False, count, fps, max_speed)
    if protect >= target or protect >= output_end:
        raise InputError(f'{clip.id}: protection must end before the last output frame')
    available = output_end-protect
    if ramp > available+1e-10:
        raise InputError(f'{clip.id}: ramp_seconds exceeds the available unprotected interval')
    if source_end < output_end:
        raise InputError(f'{clip.id}: cannot compress the displayed timeline with these frame durations')
    peak = 1+(source_end-output_end)/(available-ramp/2)
    if peak > max_speed+1e-10:
        raise InputError(f'{clip.id}: required peak speed {peak:.4f} exceeds max_speed {max_speed:g}')
    return TimeMap(source_end, output_end, protect, ramp, peak, True, count, fps, max_speed)


def add_boundary_warp(mapping, side, width, alpha):
    start = 0 if side == 'head' else mapping.source_end-width
    if start < min(mapping.protect, mapping.source_end)-1e-10:
        return 'protected_interval_priority'
    if width <= 0:
        return 'empty_window'
    proposed = mapping.speed_bound()*(1+abs(alpha))
    if proposed > mapping.max_speed+1e-10:
        return 'composed_speed_limit'
    mapping.source_warps.append((side,width,alpha))
    return 'candidate_requires_visual_review'


def select_schedule(clip, mapping):
    times = [frame['source_seconds'] for frame in clip.frames]
    selected = []
    for i in range(mapping.count):
        value = mapping.source_time(i/float(mapping.fps))
        right = bisect_left(times,value)
        if right==0:
            index=0
        elif right==len(times):
            index=len(times)-1
        else:
            index=right-1 if value-times[right-1] <= times[right]-value else right
        selected.append(index)
    selected[0],selected[-1]=0,len(times)-1
    if selected != sorted(selected):
        raise InputError(f'{clip.id}: composed source schedule is not monotonic')
    return selected
