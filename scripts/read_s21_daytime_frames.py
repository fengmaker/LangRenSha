"""Read S21 daytime sidebars as candidates, with bounded speech-frame fallback.

Original frames and OCR are evidence only. No game facts or database writes.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
import av, cv2
from rapidocr import RapidOCR
from collect_bilibili_audio import Collector, save_json
from read_s22_frame_labels import run_pass, names_in_text
from read_s21_evidence_frames import known_names, ROLES, center
from capture_s21_evidence_frames import api
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'data/reports/S21/S21_白天身份栏候选进度.json'

def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def sidebar(lines,w,h,names):
 seats=[]
 for n in range(1,13):
  row=(n-1)%6;left=n<=6
  nx=(.05 if left else .95)*w;ny=(.18+.16*row)*h
  rx=(.113 if left else .887)*w;ry=(.128+.16*row)*h
  name_lines=[l for l in lines if abs(center(l)[0]-nx)<.060*w and abs(center(l)[1]-ny)<.033*h]
  scored=[]
  for l in name_lines:
   hits=names_in_text(l['text'],names,{})
   scored.append(((bool(hits),l['confidence'],-abs(center(l)[1]-ny)),l,hits))
  chosen=max(scored,key=lambda x:x[0]) if scored else None
  hits=chosen[2] if chosen else []
  rlines=[l for l in lines if abs(center(l)[0]-rx)<.021*w and abs(center(l)[1]-ry)<.060*h]
  roles=[l for l in rlines if re.sub(r'\s','',l['text']) in ROLES]
  role=max(roles,key=lambda l:l['confidence'])['text'] if roles else None
  if role is None:
   singles=sorted([l for l in rlines if len(l['text'])==1],key=lambda l:center(l)[1]);joined=''.join(l['text'] for l in singles)
   if joined in ROLES:role=joined
  unknown=any('未知' in l['text'] or '身份未知' in l['text'] for l in rlines)
  seats.append({'seat':n,'name_candidate':hits[0][0] if len(hits)==1 else None,
    'visible_name_ocr':chosen[1]['text'] if chosen else None,'role_candidate':role,'unknown_label_candidate':unknown,
    'role_ocr_lines':rlines,'name_ocr_line':chosen[1] if chosen else None,'status':'ocr_candidate_unverified'})
 return seats

def ocr(frame,engine,names):
 p=ROOT/frame['frame_path'];sha=digest(p);assert sha==frame['frame_sha256']
 out=p.parent/'daytime_ocr'/f'{p.stem}.json'
 if out.exists():
  v=json.loads(out.read_text(encoding='utf-8'))
  if v.get('frame_sha256')==sha:return v
 im=cv2.imread(str(p));h,w=im.shape[:2];lines=[];elapsed=0
 # Only the two role/name strips: yellow player-claim summaries are outside.
 for side,x0,x1 in [('left',0,round(.137*w)),('right',round(.863*w),w)]:
  crop=cv2.resize(im[:,x0:x1],None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
  more,t=run_pass(engine,crop,f'daytime_{side}_x2',x0=x0,scale=2);lines+=more;elapsed+=t
 seats=sidebar(lines,w,h,names);roles=sum(s['role_candidate'] is not None for s in seats);plates=sum(s['name_candidate'] is not None for s in seats)
 v={**frame,'schema_version':1,'seats':seats,'role_candidates':roles,'name_candidates':plates,
  'unknown_label_candidates':sum(s['unknown_label_candidate'] for s in seats),
  'classification_candidate':'daytime_sidebar' if roles>=5 and plates>=5 else 'sidebar_not_established',
  'visual_verified':False,'ocr_lines':lines,'elapsed_seconds':round(elapsed,3),
  'note':'OCR仅定位；无栏的近景/戴盔/主持画面不能据此判断全局关视角。'}
 save_json(out,v);return v

def alternatives(entry):
 transcript=json.loads((ROOT/entry['transcript_selected_path']).read_text(encoding='utf-8'))['segments']
 cmds=[s for s in transcript if len(s['text'])<65 and re.search(r'(?:1[0-2]|[1-9一二三四五六七八九十两]+)号.*请.*发言',s['text'])
       and not re.search('准备|遗言|复盘|解说',s['text']) and .12*entry['duration_ms']<s['start_ms']<.75*entry['duration_ms']]
 result=[]
 for ratio in [.45,.65,.25]:
  available=[s for s in cmds if all(abs(s['end_ms']+12000-f['time_ms'])>15000 for f in result)]
  if not available:break
  s=min(available,key=lambda x:abs(x['start_ms']-ratio*entry['duration_ms']))
  result.append({'kind':'normal_day_numbered_speech','time_ms':s['end_ms']+12000,
   'source_segment_indices':[s['source_segment_index']],'command_text':s['text'],
   'reason':'白天真实身份栏优先；对无栏/模糊晚期镜头补看中段点名后12秒'})
 return result

def capture(entry,candidates):
 client=Collector('cookies',ROOT/'.secrets/bilibili.cookies.txt',quiet=True)
 play=api(client,'/x/player/playurl',{'bvid':entry['bvid'],'cid':entry['cid'],'fnval':16,'fnver':0,'qn':80})['data']
 tracks=play.get('dash',{}).get('video',[]);limited=[t for t in tracks if int(t.get('height',0))<=1080] or tracks
 chosen=max(limited,key=lambda t:(int(t.get('height',0)),str(t.get('codecs','')).startswith('avc')))
 folder=ROOT/f"data/extractions/S21/frames/{entry['bvid']}"
 with av.open(chosen.get('baseUrl') or chosen['base_url'],options={'headers':'Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n','rw_timeout':'20000000'}) as video:
  stream=video.streams.video[0]
  for c in candidates:
   sec=c['time_ms']/1000;p=folder/f"{entry['bvid']}_{sec:09.3f}.png"
   actual=None
   if not p.exists():
    video.seek(int(Fraction(str(sec))/stream.time_base),stream=stream,backward=True)
    for f in video.decode(stream):
     if f.time is not None and f.time>=sec:
      actual=round(f.time*1000);f.to_image().save(p);break
    else:raise ValueError('no_frame')
   yield {'frame_path':p.relative_to(ROOT).as_posix(),'frame_sha256':digest(p),'requested_time_ms':c['time_ms'],
    'actual_frame_time_ms':actual,'selection':c,'timestamp_note':None if actual else '复用既有帧，实际PTS未登记'}

def process(e,engine,names,args):
 folder=ROOT/f"data/extractions/S21/frames/{e['bvid']}";out=folder/'daytime_candidates.json'
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8'))
  if old.get('status')=='candidate_ready':return old
 cap=json.loads((folder/'capture.json').read_text(encoding='utf-8'))
 frames=[f for f in cap.get('frames',[]) if f.get('selection',{}).get('kind')=='late_numbered_speech']
 # Reuse explicitly captured normal-day searches before making new network calls.
 search=folder/'normal_day_speech_search.json'
 if search.exists():
  ss=json.loads(search.read_text(encoding='utf-8'))
  for sec in ss.get('target_seconds',[]):
   p=folder/f"{e['bvid']}_{sec:09.3f}.png"
   if p.exists():frames.append({'frame_path':p.relative_to(ROOT).as_posix(),'frame_sha256':digest(p),
    'requested_time_ms':round(sec*1000),'actual_frame_time_ms':None,'selection':{'kind':'normal_day_existing_search'}})
 checked=[];best=None
 for f in frames:
  v=ocr(f,engine,names);checked.append(v)
  if best is None or (v['role_candidates'],v['name_candidates'])>(best['role_candidates'],best['name_candidates']):best=v
  if v['role_candidates']>=10 and v['name_candidates']>=10:break
 if args.capture_fallback and (best is None or best['role_candidates']<9 or best['name_candidates']<9):
  for f in capture(e,alternatives(e)[:args.max_fallback]):
   v=ocr(f,engine,names);checked.append(v)
   if best is None or (v['role_candidates'],v['name_candidates'])>(best['role_candidates'],best['name_candidates']):best=v
   save_json(folder/'daytime_capture.json',{'bvid':e['bvid'],'cid':e['cid'],'source_path':e['selected_source_path'],
    'source_sha256':e['source_hashes']['selected_source_sha256'],'frames':[{k:v for k,v in z.items() if k not in ['seats','ocr_lines']} for z in checked]})
   if v['role_candidates']>=10 and v['name_candidates']>=10:break
 result={'bvid':e['bvid'],'cid':e['cid'],'title':e['title'],'status':'candidate_ready',
  'best_daytime_frame':best,'frames_checked':[{k:v for k,v in x.items() if k not in ['seats','ocr_lines']} for x in checked],
  'visual_verified':False,'closed_view_confirmed':False,'note':'没有识出真实底牌不等于关视角；须直接查看原图。'}
 save_json(out,result);return result

def main(args):
 entries=json.loads((ROOT/'data/reports/S21/S21_文字与截图时点索引.json').read_text(encoding='utf-8'))['entries']
 if args.bvid:entries=[e for e in entries if e['bvid'] in args.bvid]
 if args.limit:entries=entries[:args.limit]
 engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':4,'EngineConfig.onnxruntime.inter_op_num_threads':1})
 names=known_names();state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'season':'S21','items':{}}
 for e in entries:
  try:
   r=process(e,engine,names,args);b=r['best_daytime_frame'];v={'status':r['status'],'role_candidates':b['role_candidates'] if b else 0,'name_candidates':b['name_candidates'] if b else 0,'frame':b['frame_path'] if b else None}
  except Exception as err:
   v={'status':'failed','error_type':type(err).__name__}
   if any(s in str(err) for s in ['HTTP 403','HTTP 429','HTTP 412','业务状态 -412']):
    state['stopped_on_service_rejection']=True;state['items'][e['bvid']]=v;save_json(STATE,state);raise RuntimeError('service_rejected_stop') from None
  state['items'][e['bvid']]=v;state['processed']=len(state['items']);state['planned']=122
  state['with_at_least_9_role_candidates']=sum(x.get('role_candidates',0)>=9 for x in state['items'].values())
  state['updated_at_utc']=datetime.now(timezone.utc).isoformat();save_json(STATE,state)
  print(e['bvid'],v['status'],v.get('role_candidates'),v.get('name_candidates'),flush=True)
 print(json.dumps({k:v for k,v in state.items() if k!='items'},ensure_ascii=False))
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser(description=__doc__);p.add_argument('--capture-fallback',action='store_true');p.add_argument('--max-fallback',type=int,default=2,choices=[1,2,3]);p.add_argument('--limit',type=int);p.add_argument('--bvid',action='append');main(p.parse_args())