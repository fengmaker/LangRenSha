"""Render the final 1080p desktop walkthrough with Chinese narration and subtitles."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tmp'/'website_video_deps'))
import imageio_ffmpeg
SUP=Path(__file__).resolve().parent
OUT=SUP.parent
STORY=json.loads((SUP/'timeline.json').read_text(encoding='utf-8'))
RECORDINGS=json.loads((SUP/'recordings.json').read_text(encoding='utf-8'))
FF=imageio_ffmpeg.get_ffmpeg_exe()
cmd=[FF,'-y','-hide_banner','-loglevel','info','-filter_complex_threads','1']
filters=[]
for i,s in enumerate(STORY):
    duration=s['duration'];n=round(duration*30)
    if s['id'] in ('intro','outro'):
        cmd+=['-i',s['id']+'.png']
        f=f"[{i}:v]zoompan=z='1+0.012*on/{n}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={n}:s=1920x1080:fps=30,setsar=1"
    else:
        r=RECORDINGS[s['id']]
        cmd+=['-ss',str(r['trim_start']),'-t',str(duration+.1),'-i',r['path']]
        f=f"[{i}:v]fps=30,scale=1828:960:flags=lanczos,pad=1920:1080:46:48:color=0x071011,setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={n}"
    f+=f",setpts=PTS-STARTPTS,format=yuv420p,fade=t=in:st=0:d=0.16,fade=t=out:st={duration-.16}:d=0.16[v{i}]"
    filters.append(f)
cmd+=['-i','mixed_audio.wav']
filters.append(''.join(f'[v{i}]' for i in range(len(STORY)))+f'concat=n={len(STORY)}:v=1:a=0,ass=subtitles.ass[v]')
output=OUT/'大师赛档案_电脑版介绍.mp4'
cmd+=['-filter_complex',';'.join(filters),'-map','[v]','-map',f'{len(STORY)}:a',
      '-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-r','30',
      '-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','-t',str(sum(s['duration'] for s in STORY)),
      '-metadata','title=大师赛档案｜电脑版网站介绍',
      '-metadata','comment=实际电脑版页面操作录屏；中文合成旁白；字幕；原创合成背景音乐。',str(output)]
(SUP/'render_command.json').write_text(json.dumps(cmd,ensure_ascii=False,indent=2),encoding='utf-8')
with (SUP/'render.log').open('w',encoding='utf-8') as log:
    result=subprocess.run(cmd,cwd=SUP,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((SUP/'render.log').read_text(encoding='utf-8')[-7000:]);raise SystemExit(result.returncode)
print(output,output.stat().st_size,flush=True)
