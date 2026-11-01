"""Optional CPU bidirectional-flow interpolation with exact-source fallback.

This is an OpenCV classical-flow backend, not RIFE or a deformation repair model.
Only one prepared pair is cached; no external models or runtime downloads.
"""
import hashlib
import math

import cv2
import numpy as np

BACKEND_VERSION='cpu-flow-v1.2'
GATES=dict(max_analysis_side=640,min_dimension=16,min_texture_std=2.,
           cut_mae=25.,cut_correlation=.2,illumination_delta=4.,illumination_correlation=.9,
           fb_error=.75,photometric_error=20.,max_unreliable_fraction=.03,
           max_cell_unreliable_fraction=.2,max_photometric_p95=18.,max_motion_fraction=.12)


def _grid(height,width):
    y,x=np.mgrid[:height,:width].astype(np.float32)
    return np.stack((x,y),axis=-1)


def _sample(image,coordinates):
    return cv2.remap(image,coordinates[...,0],coordinates[...,1],cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REFLECT_101)


class CPUFlowInterpolator:
    """synthesize(left_rgb, right_rgb, alpha) -> (RGB uint8, JSON audit)."""
    def __init__(self):
        self._key=None
        self._pair=None

    def _prepare(self,left,right):
        height,width=left.shape[:2]
        scale=min(1.,GATES['max_analysis_side']/max(height,width))
        w,h=max(1,round(width*scale)),max(1,round(height*scale))
        a=cv2.cvtColor(cv2.resize(left,(w,h),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY)
        b=cv2.cvtColor(cv2.resize(right,(w,h),interpolation=cv2.INTER_AREA),cv2.COLOR_RGB2GRAY)
        diff=b.astype(float)-a.astype(float)
        mae=float(np.mean(abs(diff)))
        metrics=dict(analysis_size=[w,h],mae=mae)
        def reject(reason): return dict(reason=reason,confidence=0.,metrics=metrics)
        if np.array_equal(a,b): return reject('no_motion')
        if min(float(np.std(a)),float(np.std(b)))<GATES['min_texture_std']: return reject('low_texture')
        correlation=float(np.corrcoef(a.ravel()[::4],b.ravel()[::4])[0,1])
        metrics['correlation']=correlation
        if abs(float(np.median(diff)))>GATES['illumination_delta'] and correlation>GATES['illumination_correlation']:
            return reject('illumination_change')
        if mae>GATES['cut_mae'] and correlation<GATES['cut_correlation']: return reject('scene_cut_or_large_change')
        f=cv2.calcOpticalFlowFarneback(a,b,None,.5,4,21,4,7,1.5,0)
        back=cv2.calcOpticalFlowFarneback(b,a,None,.5,4,21,4,7,1.5,0)
        grid=_grid(h,w)
        displacement=np.linalg.norm(f,axis=2)
        max_motion=float(np.percentile(displacement,99))
        metrics['motion_p99']=max_motion
        if max_motion>GATES['max_motion_fraction']*min(h,w): return reject('motion_outside_confident_range')
        if max_motion<.1: return reject('no_reliable_motion')
        # Test both directions; unilateral disappearance is not an interpolation.
        bad_total=[]; photo_values=[]; max_cell=0.
        margin=max(2,int(math.ceil(max_motion))+2)
        for first,second,forward,reverse in ((a,b,f,back),(b,a,back,f)):
            destination=grid+forward
            fb=np.linalg.norm(forward+_sample(reverse,destination),axis=2)
            photo=np.abs(first.astype(float)-_sample(second,destination).astype(float))
            support=np.zeros((h,w),bool)
            support[margin:h-margin,margin:w-margin]=True
            active=np.linalg.norm(forward,axis=2)>.2
            # Include all changed pixels as well as moving ones: a disappearing
            # object must not vanish from the evidence simply because flow fails.
            support &= active | (abs(diff)>2)
            if np.count_nonzero(support)<32: return reject('insufficient_motion_support')
            bad=(fb>GATES['fb_error']) | (photo>GATES['photometric_error'])
            bad_total.extend(bad[support].tolist());photo_values.extend(photo[support].tolist())
            for y in range(margin,h-margin,16):
                for x in range(margin,w-margin,16):
                    cell=support[y:y+16,x:x+16]
                    if np.count_nonzero(cell)>=16:
                        max_cell=max(max_cell,float(np.mean(bad[y:y+16,x:x+16][cell])))
        unreliable=float(np.mean(bad_total));p95=float(np.percentile(photo_values,95))
        metrics.update(unreliable_fraction=unreliable,photometric_p95=p95,max_cell_unreliable_fraction=max_cell)
        if (unreliable>GATES['max_unreliable_fraction'] or max_cell>GATES['max_cell_unreliable_fraction']
            or p95>GATES['max_photometric_p95']): return reject('occlusion_or_inconsistent_flow')
        full_f=cv2.resize(f,(width,height),interpolation=cv2.INTER_LINEAR)*np.array([width/w,height/h],np.float32)
        full_b=cv2.resize(back,(width,height),interpolation=cv2.INTER_LINEAR)*np.array([width/w,height/h],np.float32)
        return dict(reason='interpolated',confidence=float(1-unreliable),metrics=metrics,forward=full_f,backward=full_b)

    def synthesize(self,left,right,alpha,*,source_frames=None,source_transforms=None):
        if (not isinstance(left,np.ndarray) or not isinstance(right,np.ndarray) or left.dtype!=np.uint8 or
            right.dtype!=np.uint8 or left.ndim!=3 or left.shape[-1]!=3 or left.shape!=right.shape or
            min(left.shape[:2])<GATES['min_dimension']):
            raise ValueError('Interpolation requires matching RGB uint8 frames with dimensions >=16')
        if isinstance(alpha,bool) or not isinstance(alpha,(int,float,np.floating)) or not math.isfinite(alpha) or not 0<=alpha<=1:
            raise ValueError('Interpolation alpha must be finite in [0,1]')
        composed=source_frames is not None or source_transforms is not None
        inverse_transforms=[None,None]
        if composed:
            if (not isinstance(source_frames,(tuple,list)) or len(source_frames)!=2 or
                not isinstance(source_transforms,(tuple,list)) or len(source_transforms)!=2):
                raise ValueError('Single-pass interpolation requires two source frames and transforms')
            for index,(frame,matrix) in enumerate(zip(source_frames,source_transforms)):
                if not isinstance(frame,np.ndarray) or frame.dtype!=np.uint8 or frame.shape!=left.shape:
                    raise ValueError('Source interpolation frames must match stabilized RGB dimensions')
                matrix=np.asarray(matrix,dtype=np.float64)
                if matrix.shape!=(2,3) or not np.all(np.isfinite(matrix)) or abs(np.linalg.det(matrix[:,:2]))<1e-10:
                    raise ValueError('Source transform must be a finite nonsingular 2x3 affine matrix')
                inverse_transforms[index]=cv2.invertAffineTransform(matrix)
        alpha=float(alpha)
        audit=dict(backend='cpu_flow',version=BACKEND_VERSION,opencv_version=cv2.__version__,alpha=alpha,
                   applied=False,confidence=1.,reason='source_endpoint',metrics={},image_resampler='opencv_lanczos4',
                   single_pass_composition=composed,source_resample_passes=0)
        if alpha in (0.,1.): return (left if alpha==0 else right).copy(),audit
        nearest=left if alpha<=.5 else right
        key=(left.shape,hashlib.sha256(left.tobytes()).digest(),hashlib.sha256(right.tobytes()).digest())
        if key!=self._key:
            try:
                self._pair=self._prepare(left,right);self._key=key
            except cv2.error:
                self._key=None;self._pair=None
                audit.update(reason='backend_error',confidence=0.)
                return nearest.copy(),audit
        pair=self._pair
        audit.update({k:pair[k] for k in ('reason','confidence','metrics')})
        if pair['reason']!='interpolated': return nearest.copy(),audit
        height,width=left.shape[:2];grid=_grid(height,width)
        def warp(frame,flow,amount,inverse):
            # Invert x_target=x_source+amount*flow(x_source) iteratively.
            coordinates=grid-amount*flow
            for _ in range(3): coordinates=grid-amount*_sample(flow,coordinates)
            if inverse is not None:
                coordinates=(coordinates@inverse[:,:2].T+inverse[:,2]).astype(np.float32)
            return cv2.remap(frame,coordinates[...,0],coordinates[...,1],cv2.INTER_LANCZOS4,
                             borderMode=cv2.BORDER_REFLECT_101).astype(np.float32)
        try:
            originals=source_frames if composed else (left,right)
            reference=0 if alpha<=.5 else 1
            frame=warp(originals[reference],pair['forward'] if reference==0 else pair['backward'],
                       alpha if reference==0 else 1-alpha,inverse_transforms[reference])
        except cv2.error:
            audit.update(reason='backend_error',confidence=0.)
            return nearest.copy(),audit
        # Source exposures can have different acquired sampling/detail. Averaging
        # their aligned pixels destroys detail even with correct motion. With
        # occlusion already rejected, reconstruct from the nearest exposure only;
        # the reverse flow remains an independent consistency check.
        frame=np.clip(np.rint(frame),0,255).astype(np.uint8)
        audit['applied']=True
        audit['source_resample_passes']=1
        audit['reference_policy']='nearest_source_motion_compensation'
        audit['color_reference']='left' if reference==0 else 'right'
        audit['opposite_source_role']='bidirectional_flow_validation_only'
        return frame,audit


def create_backend(name='cpu_flow'):
    if name!='cpu_flow': raise ValueError(f'Interpolation backend is not installed/configured: {name}')
    return CPUFlowInterpolator()
