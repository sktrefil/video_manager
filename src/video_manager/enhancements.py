"""Versioned, opt-in pixel processing options shared by JSON, CLI and renderer."""
from .errors import InputError
from .time_map import number


def normalize_enhancements(value=None):
    if value is None:value={}
    def fields(obj,allowed,label):
        if not isinstance(obj,dict) or set(obj)-set(allowed):
            raise InputError(f'Invalid {label} options')
    fields(value,('interpolation','stabilization','watermark'),'enhancements')
    interpolation=value.get('interpolation',{})
    stabilization=value.get('stabilization',{})
    watermark=value.get('watermark',{})
    fields(interpolation,('enabled','backend'),'interpolation')
    fields(stabilization,('enabled','strength','smoothing_seconds','max_crop_fraction'),'stabilization')
    fields(watermark,('enabled','profile','regions','center_x_fraction','center_y_fraction','width_fraction','height_fraction'),'watermark')
    for name,options in [('interpolation',interpolation),('stabilization',stabilization),('watermark',watermark)]:
        if not isinstance(options.get('enabled',False),bool):
            raise InputError(f'{name}.enabled must be boolean')
    backend=interpolation.get('backend','cpu_flow')
    if backend!='cpu_flow':
        raise InputError('Interpolation backend unavailable; supported backend: cpu_flow')
    strength=number(stabilization.get('strength',.7),'stabilization.strength')
    smooth=number(stabilization.get('smoothing_seconds',.4),'stabilization.smoothing_seconds',positive=True)
    crop=number(stabilization.get('max_crop_fraction',.05),'stabilization.max_crop_fraction')
    if strength>1 or not .05<=smooth<=2 or crop>.15:
        raise InputError('Stabilization requires strength 0..1, smoothing 0.05..2s, crop 0..0.15')
    profile=watermark.get('profile','gemini')
    if profile not in ('gemini','hailuo','both','custom','both_inpaint'):
        raise InputError('Watermark profile must be gemini, hailuo, both or custom')
    defaults=dict(hailuo=(.89,.932,.20,.065),gemini=(.90625,5/6,.055,.10),
                  both=(.90625,5/6,.055,.10),custom=(.90625,5/6,.055,.10),
                  both_inpaint=(.90625,5/6,.055,.10))[profile]
    center_x=number(watermark.get('center_x_fraction',defaults[0]),'watermark.center_x_fraction')
    center_y=number(watermark.get('center_y_fraction',defaults[1]),'watermark.center_y_fraction')
    mask_width=number(watermark.get('width_fraction',defaults[2]),'watermark.width_fraction',positive=True)
    mask_height=number(watermark.get('height_fraction',defaults[3]),'watermark.height_fraction',positive=True)
    if (mask_width>.25 or mask_height>.25 or center_x-mask_width/2<0 or center_x+mask_width/2>1
            or center_y-mask_height/2<0 or center_y+mask_height/2>1):
        raise InputError('Watermark mask must fit inside the frame and cover at most 25% per dimension')
    normalized_watermark=dict(enabled=watermark.get('enabled',False),center_x_fraction=center_x,
                       center_y_fraction=center_y,width_fraction=mask_width,height_fraction=mask_height)
    if 'profile' in watermark:normalized_watermark['profile']=profile
    if 'regions' in watermark:
        from .watermark_crop import validate_regions
        if profile not in ('both','both_inpaint'):
            raise InputError('Custom watermark regions require the both or both_inpaint profile')
        normalized_watermark['regions']=validate_regions(watermark['regions'])
    return dict(interpolation=dict(enabled=interpolation.get('enabled',False),backend=backend),
        stabilization=dict(enabled=stabilization.get('enabled',False),strength=strength,
                           smoothing_seconds=smooth,max_crop_fraction=crop),
        watermark=normalized_watermark)


def enhancements_enabled(options):
    return (options['interpolation']['enabled'] or options['stabilization']['enabled']
            or options['watermark']['enabled'])
