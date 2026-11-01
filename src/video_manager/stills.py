"""Save still images from rendered video outputs."""
from pathlib import Path

import cv2

from .errors import ToolError


def save_last_frame(video_path: Path, image_path: Path) -> Path:
    """Decode and save the final displayed frame of a rendered video as PNG."""
    video_path=Path(video_path)
    image_path=Path(image_path)
    capture=cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise ToolError(f'Could not open rendered video to save its last frame: {video_path.name}')
        frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count<1:
            raise ToolError(f'Rendered video has no decodable frames: {video_path.name}')
        capture.set(cv2.CAP_PROP_POS_FRAMES,frame_count-1)
        ok,frame=capture.read()
        if not ok or frame is None:
            raise ToolError(f'Could not decode the final frame of {video_path.name}')
        image_path.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(image_path),frame):
            raise ToolError(f'Could not save the final frame image: {image_path.name}')
    finally:
        capture.release()
    return image_path
