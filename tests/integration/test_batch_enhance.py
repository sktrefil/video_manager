import copy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from video_manager.batch_enhance import process_video,is_completed,load_regions,save_regions
from video_manager.probe import probe
from video_manager.render import Encoder,decode_frames
from video_manager.tools import run_tool
from video_manager.watermark_crop import DEFAULT_REGIONS


class BatchEnhanceTests(unittest.TestCase):
    def test_encoded_result_audio_crop_and_completion_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);silent=root/'silent.mp4';source=root/'source.mp4';output=root/'result.mp4'
            encoder=Encoder(silent,320,180,Fraction(12))
            try:
                for i in range(12):
                    frame=np.full((180,320,3),40+i,np.uint8)
                    for x,y,w,h in DEFAULT_REGIONS:
                        frame[int(y*180):int((y+h)*180)+1,int(x*320):int((x+w)*320)+1]=(255,0,0)
                    encoder.write(frame.tobytes())
            finally:encoder.close()
            run_tool(['ffmpeg','-v','error','-nostdin','-i',str(silent),'-f','lavfi','-i',
                      'sine=frequency=440:duration=1','-c:v','copy','-c:a','aac','-shortest',str(source)])
            settings={'watermark':{'enabled':True,'profile':'both'}}
            self.assertFalse(is_completed(source,output,settings))
            process_video(source,output,settings)
            result=probe(output,'output')
            self.assertTrue(result.has_audio)
            self.assertEqual((result.width,result.height,len(result.frames)),(320,180,12))
            for data in decode_frames(result,320,180):
                frame=np.frombuffer(data,np.uint8).reshape(180,320,3)
                self.assertFalse(np.any((frame[:,:,0]>180)&(frame[:,:,1]<80)&(frame[:,:,2]<80)))
            self.assertTrue(is_completed(source,output,settings))
            changed=copy.deepcopy(settings);changed['watermark']['regions']=[]
            self.assertFalse(is_completed(source,output,changed))
            record_path=Path(str(output)+'.json')
            record=json.loads(record_path.read_text(encoding='utf-8'))
            self.assertGreater(record['effects'][0]['watermark']['retained_area_fraction'],.7)
            record['engine']='older-version';record_path.write_text(json.dumps(record),encoding='utf-8')
            self.assertFalse(is_completed(source,output,settings))
            process_video(source,output,changed)
            self.assertTrue(is_completed(source,output,changed))
            record_path.unlink()
            self.assertFalse(is_completed(source,output,changed))

    def test_region_settings_survive_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'nested'/'result.mp4'
            self.assertIsNone(load_regions(output))
            save_regions(output,[DEFAULT_REGIONS[1]])
            self.assertEqual(load_regions(output),[list(DEFAULT_REGIONS[1])])
            save_regions(output,[])
            self.assertEqual(load_regions(output),[])


if __name__=='__main__':unittest.main()
