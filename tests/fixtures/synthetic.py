"""Small deterministic shared-endpoint clips; no downloaded fixtures."""
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageDraw
from video_manager.render import Encoder


def make_sequence(directory: Path, count=4):
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for clip in range(count):
        path = directory / f'클립 {clip + 1}.mp4'
        encoder = Encoder(path, 160, 96, Fraction(10))
        try:
            for frame in range(10):
                # Globally indexed state means one clip's endpoint equals the next's start.
                state = clip * 9 + frame
                image = Image.new('RGB', (160, 96), (20 + state * 3, 25, 60))
                draw = ImageDraw.Draw(image)
                draw.rectangle((10 + state * 2, 40, 20 + state * 2, 60), fill=(240, 200, 40))
                draw.text((5, 76), f'state={state:02d}', fill='white')
                encoder.write(image.tobytes())
        finally:
            encoder.close()
        paths.append(path)
    return paths


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    for path in make_sequence(args.directory):
        print(path)


def make_motion_clip(path: Path, start: float, end: float, count=40, fps=20):
    """Textured translating object; shared positions give matching endpoint images."""
    encoder = Encoder(path, 160, 96, Fraction(fps))
    try:
        for frame in range(count):
            position = round(start+(end-start)*frame/max(1, count-1))
            image = Image.new('RGB', (160, 96), (20, 20, 20))
            draw = ImageDraw.Draw(image)
            for y in range(0, 24, 4):
                for x in range(0, 24, 4):
                    color = (230, 190, 60) if (x+y)//4 % 2 else (90, 170, 230)
                    draw.rectangle((position+x, 36+y, position+x+3, 36+y+3), fill=color)
            encoder.write(image.tobytes())
    finally:
        encoder.close()
    return path


def make_positions_clip(path: Path, positions, fps=20):
    encoder=Encoder(path,160,96,Fraction(fps))
    try:
        for position in positions:
            image=Image.new('RGB',(160,96),(20,20,20))
            draw=ImageDraw.Draw(image)
            for y in range(0,24,4):
                for x in range(0,24,4):
                    color=(230,190,60) if (x+y)//4%2 else (90,170,230)
                    draw.rectangle((round(position)+x,36+y,round(position)+x+3,36+y+3),fill=color)
            encoder.write(image.tobytes())
    finally:
        encoder.close()
    return path
