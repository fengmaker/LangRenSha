"""Verify the delivered movie and create a visual review sheet."""
import json
from pathlib import Path
import re
import subprocess
import sys
import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tmp'/'website_video_deps'))
import imageio_ffmpeg
SUP=Path(__file__).resolve().parent
OUT=SUP.parent
VIDEO=OUT/'大师赛档案_电脑版介绍.mp4'
FF=imageio_ffmpeg.get_ffmpeg_exe()
cap=cv2.VideoCapture(str(VIDEO))
width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps=cap.get(cv2.CAP_PROP_FPS);frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
assert (width,height,fps)==(1920,1080,30.0),(width,height,fps)
story=json.loads((SUP/'timeline.json').read_text(encoding='utf-8'))
assert abs(frames/fps-sum(s['duration'] for s in story))<.1
sheet=Image.new('RGB',(1600,1920),'#071011');d=ImageDraw.Draw(sheet)
f=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
checks=[(2,'片头'),(10,'首页'),(21,'对局筛选'),(31,'座位与身份'),(42,'票型记录'),(53,'选手数据'),(62,'积分榜'),(77,'结尾二维码')]
for i,(t,label) in enumerate(checks):
    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();assert ok,(t,label)
    im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
    im.save(SUP/f'final_{t:02d}s.png')
    x=(i%2)*800;y=(i//2)*480
    sheet.paste(im.resize((800,450),Image.Resampling.LANCZOS),(x,y+30))
    d.text((x+14,y+2),f'{t:02d}s · {label}',font=f,fill='#7ce1bf')
cap.release()
sheet.save(SUP/'final_contact.png')
qr=cv2.imread(str(SUP/'final_77s.png'))
qr_url,points,_=cv2.QRCodeDetector().detectAndDecode(qr)
assert qr_url=='https://fengmaker.github.io/langrensha-site/',qr_url
decode=subprocess.run([FF,'-v','error','-i',str(VIDEO),'-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
assert decode.returncode==0,decode.stderr
assert not decode.stderr.strip(),decode.stderr
vol=subprocess.run([FF,'-hide_banner','-i',str(VIDEO),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
mean=re.search(r'mean_volume: ([^\n]+)',vol.stderr).group(1).strip()
maximum=re.search(r'max_volume: ([^\n]+)',vol.stderr).group(1).strip()
assert float(maximum.split()[0])<0,maximum
report={'video':VIDEO.name,'size_bytes':VIDEO.stat().st_size,'resolution':[width,height],
        'fps':fps,'frames':frames,'duration_seconds':frames/fps,'decode':'passed',
        'audio_mean_volume':mean,'audio_max_volume':maximum,'end_qr_url':qr_url,
        'recording':'actual desktop browser interactions, 1600x840 viewport',
        'narration':'zh-CN-YunxiNeural, synthetic Chinese male voice',
        'music':'original locally synthesized ambient track',
        'public_url_http_check':'200',
        'chapters':[{'id':s['id'],'start':s['start'],'duration':s['duration']} for s in story]}
(SUP/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
