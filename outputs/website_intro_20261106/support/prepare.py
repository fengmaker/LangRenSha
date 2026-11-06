"""Prepare timed narration, subtitles, original ambient audio and title cards."""
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import wave
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tmp" / "website_video_deps"))
import imageio_ffmpeg
import qrcode

OUT = Path(__file__).resolve().parents[1]
SUP = OUT / "support"
STORY = json.loads((SUP / "storyboard.json").read_text(encoding="utf-8"))
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS, SR = 30, 48000
URL = "https://fengmaker.github.io/langrensha-site/"
MINT, WHITE, MUTED = "#7ce1bf", "#f0f1e9", "#a0b1aa"

def font(size, bold=False):
    return ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc", size)

def background():
    y, x = np.mgrid[0:1080, 0:1920]
    glow = np.exp(-((x-1490)**2/(900**2)+(y-460)**2/(780**2)))
    rgb = np.stack([7+glow*3, 16+glow*14, 17+glow*12], axis=2).astype(np.uint8)
    im = Image.fromarray(rgb)
    d = ImageDraw.Draw(im)
    for xx in range(0,1920,80):
        d.line((xx,0,xx,1080), fill=(13,29,28), width=1)
    for yy in range(0,1080,80):
        d.line((0,yy,1920,yy), fill=(13,29,28), width=1)
    d.line((88,137,1832,137),fill="#23403a",width=1)
    d.rectangle((88,68,128,108),outline=MINT,width=2)
    d.text((95,72),"M",font=font(23,True),fill=MINT)
    d.text((148,68),"大师赛档案",font=font(28,True),fill=WHITE)
    d.text((1505,75),"电脑版 · 功能介绍",font=font(22),fill=MUTED)
    return im

def chips(d, xy, labels, size=26):
    x,y = xy
    f=font(size)
    for label in labels:
        w=int(d.textlength(label,font=f))+42
        d.rounded_rectangle((x,y,x+w,y+58),radius=8,fill="#102823",outline="#31564a",width=1)
        d.text((x+21,y+12),label,font=f,fill=MINT)
        x+=w+16

def orbit(d, cx, cy):
    for r in [212,324,394]:
        d.ellipse((cx-r,cy-r,cx+r,cy+r),outline="#234d41",width=2 if r==324 else 1)
    for k in range(12):
        a=k*math.pi/6-math.pi/2
        x,y=cx+324*math.cos(a),cy+324*math.sin(a)
        d.ellipse((x-30,y-30,x+30,y+30),fill="#102c25",outline="#467a68",width=2)
        txt=f"{k+1:02d}"
        d.text((x,y),txt,font=font(20,True),fill=MINT,anchor="mm")
    d.ellipse((cx-145,cy-145,cx+145,cy+145),fill="#10251f",outline="#42745f",width=2)
    d.text((cx,cy-12),"档 案",font=font(54,True),fill=MINT,anchor="mm")
    d.text((cx,cy+62),"12 个座位 · 一局故事",font=font(21),fill=MUTED,anchor="mm")

im=background(); d=ImageDraw.Draw(im)
d.text((88,205),"分享一个给狼人杀观众的网站",font=font(28),fill=MINT)
d.text((82,292),"比赛看过了，",font=font(86,True),fill=WHITE)
d.text((82,414),"细节还记得吗？",font=font(86,True),fill=MINT)
d.text((88,571),"找比赛、看票型、查选手。",font=font(34),fill=MUTED)
chips(d,(88,665),["真实页面录屏","中文讲解"])
d.text((88,854),"每一局，都有迹可循。",font=font(39,True),fill=WHITE)
orbit(d,1425,548)
im.save(SUP/"intro.png")

im=background(); d=ImageDraw.Draw(im)
d.text((88,218),"分享给一起看比赛的人",font=font(28),fill=MINT)
d.text((82,310),"大师赛档案",font=font(88,True),fill=WHITE)
d.text((86,443),"每一局，都有迹可循。",font=font(58,True),fill=MINT)
chips(d,(88,577),["找一场比赛","复盘一轮票型","了解一位选手"],24)
d.text((88,719),"fengmaker.github.io/langrensha-site/",font=font(41),fill=WHITE)
d.text((88,802),"独立数据档案 · 统计范围与口径详见站内说明",font=font(24),fill=MUTED)
qr=qrcode.QRCode(box_size=12,border=3,error_correction=qrcode.constants.ERROR_CORRECT_M)
qr.add_data(URL);qr.make(fit=True)
qi=qr.make_image(fill_color="#071011",back_color="white").convert("RGB").resize((326,326),Image.Resampling.NEAREST)
im.paste(qi,(1448,330))
d.text((1611,707),"扫码打开网站",font=font(28,True),fill=MINT,anchor="mm")
d.text((1611,758),"也可以复制左侧网址",font=font(21),fill=MUTED,anchor="mm")
im.save(SUP/"outro.png")

im=background();d=ImageDraw.Draw(im)
d.text((88,228),"狼人杀观众的复盘工具",font=font(28),fill=MINT)
d.text((82,330),"看大师赛，",font=font(84,True),fill=WHITE)
d.text((82,452),"用这个网站复盘",font=font(76,True),fill=MINT)
chips(d,(88,638),["对局档案","日夜票型","选手数据"],24)
d.text((88,851),"大师赛档案",font=font(45,True),fill=WHITE)
shot=Image.open(SUP/"screenshots"/"game_vote.png").convert("RGB").crop((90,0,1350,900)).resize((740,529),Image.Resampling.LANCZOS)
im.paste(shot,(1088,257));d=ImageDraw.Draw(im)
d.rounded_rectangle((1084,219,1832,792),radius=12,outline="#4b8c73",width=2)
d.text((1110,227),"日夜事件与票型记录",font=font(21),fill=MINT)
im.save(OUT/"大师赛档案_视频封面.png")

def time_srt(sec):
    n=round(sec*1000);return f"{n//3600000:02d}:{n//60000%60:02d}:{n//1000%60:02d},{n%1000:03d}"
def time_ass(sec):
    n=round(sec*100);return f"{n//360000}:{n//6000%60:02d}:{n//100%60:02d}.{n%100:02d}"

audio=[];cues=[];t=0.0
for scene in STORY:
    raw=subprocess.check_output([FF,"-v","error","-i",str(SUP/"audio"/(scene["id"]+".mp3")),"-f","s16le","-ac","1","-ar",str(SR),"-"])
    samples=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768
    lead=0.45;tail=1.8 if scene["id"]=="outro" else 0.65
    duration=math.ceil((len(samples)/SR+lead+tail)*FPS)/FPS
    scene.update(start=t,duration=duration,audio_start=t+lead)
    padded=np.zeros(round(duration*SR),np.float32)
    padded[round(lead*SR):round(lead*SR)+len(samples)]=samples
    audio.append(padded)
    boundaries=json.loads((SUP/"audio"/(scene["id"]+".json")).read_text(encoding="utf-8"))
    narration=scene["narration"];pos=0;words=[]
    for b in boundaries:
        index=narration.find(b["text"],pos)
        if index<0:raise ValueError((scene["id"],b["text"]))
        end=index+len(b["text"])
        words.append((index,end,b["offset"]/1e7,(b["offset"]+b["duration"])/1e7))
        pos=end
    group=[]
    for j,w in enumerate(words):
        group.append(w)
        next_start=words[j+1][0] if j+1<len(words) else len(narration)
        punctuation=narration[w[1]:next_start]
        length=w[1]-group[0][0]
        if j==len(words)-1 or length>=23 or (length>=8 and punctuation):
            text=narration[group[0][0]:next_start].strip()
            cues.append({"start":t+lead+group[0][2],"end":min(t+duration-0.15,t+lead+w[3]+0.20),"text":text})
            group=[]
    t+=duration

narration=np.concatenate(audio);duration=len(narration)/SR
for i in range(len(cues)-1):
    cues[i]['end']=min(cues[i]['end'],cues[i+1]['start']-.03)
peak=np.max(np.abs(narration));narration*=0.86/peak
music=np.zeros_like(narration)
# This quiet score is synthesized here; it uses no downloaded music or samples.
chords=[[220,261.6256,329.6276],[174.6141,220,261.6256],[130.8128,164.8138,195.9977],[195.9977,246.9417,293.6648]]
for beat, start in enumerate(np.arange(0,duration,2.0)):
    notes=chords[(beat//4)%4];freq=notes[beat%3]*2
    count=min(round(3.5*SR),len(music)-round(start*SR))
    ts=np.arange(count)/SR
    env=(1-np.exp(-ts*22))*np.exp(-ts*1.6)
    tone=(np.sin(2*np.pi*freq*ts)+0.22*np.sin(4*np.pi*freq*ts))*env*0.016
    music[round(start*SR):round(start*SR)+count]+=tone
for bar,start in enumerate(np.arange(0,duration,8.0)):
    count=min(round(9*SR),len(music)-round(start*SR));ts=np.arange(count)/SR
    env=np.minimum(ts/1.5,1)*np.minimum((9-ts)/2,1)
    for freq in chords[bar%4]:
        music[round(start*SR):round(start*SR)+count]+=np.sin(2*np.pi*freq*ts)*env*0.0028
fade=np.minimum(np.arange(len(music))/SR/1.5,1)*np.minimum((len(music)-np.arange(len(music)))/SR/2.0,1)
mixed=np.clip(narration+music*fade,-1,1)
with wave.open(str(SUP/"mixed_audio.wav"),"wb") as f:
    f.setnchannels(1);f.setsampwidth(2);f.setframerate(SR);f.writeframes((mixed*32767).astype("<i2").tobytes())
(SUP/"timeline.json").write_text(json.dumps(STORY,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"大师赛档案_字幕.srt").write_text("\n\n".join(f"{j+1}\n{time_srt(c['start'])} --> {time_srt(c['end'])}\n{c['text']}" for j,c in enumerate(cues))+"\n",encoding="utf-8")
ass="""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Microsoft YaHei,36,&H00F0F1E9,&H00F0F1E9,&H80071011,&H80071011,0,0,0,0,100,100,0,0,3,10,0,2,70,70,18,1
Style: Brand,Microsoft YaHei,22,&H00AAB1A0,&H00AAB1A0,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,7,40,40,10,1
Style: Chapter,Microsoft YaHei,22,&H00BFE17C,&H00BFE17C,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,40,40,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
for c in cues:
    ass+=f"Dialogue: 2,{time_ass(c['start'])},{time_ass(c['end'])},Sub,,0,0,0,,{{\\fad(80,80)}}{c['text']}\n"
for s in STORY[1:-1]:
    ass+=f"Dialogue: 1,{time_ass(s['start'])},{time_ass(s['start']+s['duration'])},Brand,,0,0,0,,大师赛档案 · 电脑版功能介绍\n"
    ass+=f"Dialogue: 1,{time_ass(s['start'])},{time_ass(s['start']+s['duration'])},Chapter,,0,0,0,,{s['kicker']}\n"
(SUP/"subtitles.ass").write_text(ass,encoding="utf-8")
print(json.dumps({"duration":duration,"chapters":[{"id":s['id'],"duration":s['duration']} for s in STORY]},ensure_ascii=False),flush=True)
