"""Thin test adapter; decisions are delegated to real product code."""
import numpy as np

from video_manager.frame_effects import interpolation_guard
from video_manager.interpolation import create_backend
from video_manager.stabilization import plan_from_frames,apply_transform


def interpolate(left,right,alpha,*,confidence,cut):
    reason=interpolation_guard(dict(cut=cut,abstain_reason='scene_cut' if cut else '',
                                    confidence=confidence,dt=.05),.05)
    if reason:
        return dict(frame=left if alpha<=.5 else right,applied=False,reason=reason)
    frame,audit=create_backend('cpu_flow').synthesize(left,right,alpha)
    return dict(frame=frame,**audit)


def stabilize(frames,times,*,max_crop_fraction,smoothing_seconds,strength,protect_seconds):
    plan=plan_from_frames(frames,times,crop_budget=max_crop_fraction,smooth_seconds=smoothing_seconds,
                          strength=strength,protect_seconds=protect_seconds)
    result=np.array([apply_transform(frame,matrix) for frame,matrix in zip(frames,plan['transforms'])])
    return dict(frames=result,transforms=plan['transforms'],**plan['audit'])
