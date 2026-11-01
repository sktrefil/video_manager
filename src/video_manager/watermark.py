"""Remove a fixed-position visible mark before geometric video effects."""
import cv2
import numpy as np


def mark_mask(clip,width,height,options):
    """Map fixed logo masks or selected regions through render's fit-and-pad geometry."""
    display_width=clip.width*float(clip.sample_aspect_ratio)
    scale=min(width/display_width,height/clip.height)
    fitted_width=display_width*scale
    fitted_height=clip.height*scale
    left=(width-fitted_width)/2
    top=(height-fitted_height)/2
    mask=np.zeros((height,width),dtype=np.uint8)
    bounds=[]

    def add_region(draw_region,bounds_region):
        x0,y0,x1,y1=bounds_region
        if x0>=x1 or y0>=y1:return
        local=np.zeros((height,width),dtype=np.uint8)
        draw_region(local)
        edge=max(3,round(min(x1-x0,y1-y0)*.10))
        if edge%2==0:edge+=1
        local=cv2.dilate(local,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(edge,edge)))
        cv2.bitwise_or(mask,local,dst=mask)
        bounds.append((x0,y0,x1,y1))

    regions=options.get('regions')
    if regions is not None:
        for rx,ry,rw,rh in regions:
            x0=max(0,round(left+rx*fitted_width));x1=min(width,round(left+(rx+rw)*fitted_width))
            y0=max(0,round(top+ry*fitted_height));y1=min(height,round(top+(ry+rh)*fitted_height))
            add_region(lambda target:cv2.rectangle(target,(x0,y0),(x1-1,y1-1),255,-1),(x0,y0,x1,y1))
    else:
        profiles=('gemini','hailuo') if options.get('profile')=='both_inpaint' else (options.get('profile','gemini'),)
        for profile in profiles:
            defaults=dict(hailuo=(.89,.932,.20,.065),gemini=(.90625,5/6,.055,.10),
                          both_inpaint=(.90625,5/6,.055,.10),custom=(.90625,5/6,.055,.10))
            cx,cy,rw,rh=(options['center_x_fraction'],options['center_y_fraction'],
                         options['width_fraction'],options['height_fraction']) if profile=='custom' else defaults[profile]
            x=left+cx*fitted_width;y=top+cy*fitted_height
            half_width=rw*fitted_width/2;half_height=rh*fitted_height/2
            x0=max(0,round(x-half_width));x1=min(width,round(x+half_width))
            y0=max(0,round(y-half_height));y1=min(height,round(y+half_height))
            if x0>=x1 or y0>=y1:continue
            if profile=='hailuo':
                add_region(lambda target:cv2.rectangle(target,(x0,y0),(x1-1,y1-1),255,-1),(x0,y0,x1,y1))
            else:
                radius_x=.78*half_width;radius_y=.75*half_height
                outline=[(0,-1),(.185,-.556),(.37,-.37),(.556,-.185),(1,0),
                         (.556,.185),(.37,.37),(.185,.556),(0,1),(-.185,.556),
                         (-.37,.37),(-.556,.185),(-1,0),(-.556,-.185),(-.37,-.37),(-.185,-.556)]
                points=np.array([(round(x+dx*radius_x),round(y+dy*radius_y)) for dx,dy in outline],dtype=np.int32)
                add_region(lambda target:cv2.fillPoly(target,[points],255),(x0,y0,x1,y1))
    if bounds:
        x0=min(box[0] for box in bounds);y0=min(box[1] for box in bounds)
        x1=max(box[2] for box in bounds);y1=max(box[3] for box in bounds)
    else:x0=y0=x1=y1=0
    return mask,dict(left=x0,top=y0,width=x1-x0,height=y1-y0)


def remove_mark(frame,mask):
    if not np.any(mask):return frame.copy()
    return cv2.inpaint(frame,mask,5,cv2.INPAINT_NS)
