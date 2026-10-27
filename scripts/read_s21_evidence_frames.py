"""OCR only S21 evidence candidates; every identity still needs visual review."""
from __future__ import annotations
import argparse,csv,hashlib,json,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
import cv2
from rapidocr import RapidOCR
from collect_bilibili_audio import save_json
from read_s22_frame_labels import run_pass,norm,names_in_text
ROOT=Path(__file__).resolve().parents[1]
CAPTURE=ROOT/'data/reports/S21_截图采集进度.json';STATE=ROOT/'data/reports/S21_画面OCR候选进度.json'
ROLES={'狼人','平民','预言家','女巫','猎人','白神','白痴','混血儿','守卫','狼王','黑狼王','骑士','机械狼','通灵师','机械女巫','机械猎人','机械守卫','机械通灵师','机械平民','傀儡','诡术师','鬼术师','魔术师','定序王子','舞者','假面','盗宝大师','盗贼','鬼魂新娘'}
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def center(l):
 return sum(x[0] for x in l['bbox'])/4,sum(x[1] for x in l['bbox'])/4

def known_names():
 result=set()
 p=ROOT/'data/weibo/2026-02-24_2026-05-26/S21_姓名照片来源索引.csv'
 with p.open(encoding='utf-8-sig',newline='') as f:
  for row in csv.DictReader(f):
   if row.get('included_for_review')!='true':continue
   for key in ['nameplate_read_texts','normalized_names_from_nameplate']:
    text=row.get(key,'')
    try:words=json.loads(text)
    except (ValueError,TypeError):words=re.split('[|、,，;；]',text)
    if isinstance(words,str):words=[words]
    if isinstance(words,list):result.update(str(w).strip() for w in words if str(w).strip())
 return sorted(result)

def grid(lines,w,h,names):
 result=[]
 for n in range(1,13):
  col=(n-1)%4;row=(n-1)//4
  rx=[.207,.364,.520,.679][col]*w;ry=[.345,.523,.700][row]*h
  nx=[.261,.418,.574,.734][col]*w;ny=[.387,.565,.742][row]*h
  role_lines=[l for l in lines if abs(center(l)[0]-rx)<.027*w and abs(center(l)[1]-ry)<.061*h]
  valid_roles=[l for l in role_lines if re.sub(r'\s','',l['text']) in ROLES]
  role=max(valid_roles,key=lambda l:l['confidence'])['text'] if valid_roles else None
  if role is None:
   singles=sorted([l for l in role_lines if len(l['text'])==1],key=lambda l:center(l)[1]);joined=''.join(l['text'] for l in singles)
   if joined in ROLES:role=joined
  name_lines=[l for l in lines if abs(center(l)[0]-nx)<.077*w and abs(center(l)[1]-ny)<.032*h]
  scored=[]
  for l in name_lines:
   found=names_in_text(l['text'],names,{})
   scored.append(((bool(found),l['confidence'],-abs(center(l)[1]-ny)),l,found))
  chosen=max(scored,key=lambda x:x[0]) if scored else None
  found=chosen[2] if chosen else [];canonical=found[0][0] if len(found)==1 else None
  result.append({'seat':n,'name_candidate':canonical,'visible_name_ocr':chosen[1]['text'] if chosen else None,'role_candidate':role,
   'role_ocr_lines':role_lines,'name_ocr_line':chosen[1] if chosen else None,'status':'ocr_candidate_unverified'})
 return result

def process_frame(frame,engine,names):
 p=ROOT/frame['frame_path'];assert digest(p)==frame['frame_sha256'];out=p.parent/'ocr'/f'{p.stem}.json'
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8'))
  if old.get('frame_sha256')==frame['frame_sha256'] and old.get('schema_version')==1:return old
 image=cv2.imread(str(p));h,w=image.shape[:2];lines,elapsed=run_pass(engine,image,'full_frame')
 seats=grid(lines,w,h,names);roles=sum(s['role_candidate'] is not None for s in seats);plates=sum(s['name_candidate'] is not None for s in seats)
 is_grid=roles>=5 and plates>=3
 if is_grid:
  for row,cy in enumerate([.387,.565,.742]):
   y0=max(0,round((cy-.025)*h));y1=min(h,round((cy+.030)*h));x0=round(.225*w);x1=round(.79*w)
   crop=cv2.resize(image[y0:y1,x0:x1],None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
   more,extra=run_pass(engine,crop,f'settlement_names_row{row+1}_x2',x0=x0,y0=y0,scale=2)
   lines+=more;elapsed+=extra
  seats=grid(lines,w,h,names);roles=sum(s['role_candidate'] is not None for s in seats);plates=sum(s['name_candidate'] is not None for s in seats)
 winner=None
 for l in lines:
  t=l['text']
  if '好人胜利' in t or '好人阵营获胜' in t:winner='good'
  if '狼人胜利' in t or '狼人阵营获胜' in t:winner='werewolf'
 v={'schema_version':1,'frame_path':frame['frame_path'],'frame_sha256':frame['frame_sha256'],'requested_time_ms':frame['requested_time_ms'],
  'actual_frame_time_ms':frame.get('actual_frame_time_ms'),'classification_candidate':'settlement_grid_4x3' if is_grid else 'not_settlement_grid',
  'grid_role_candidates':roles,'grid_name_candidates':plates,'winner_ocr_candidate':winner,'seats':seats if is_grid else [],
  'ocr_lines':lines,'elapsed_seconds':round(elapsed,3),'visual_verified':False,'note':'OCR仅作定位与对照，不直接写入身份/座位/胜负事实。'}
 save_json(out,v);return v

def process(entry,capture,engine,names):
 b=entry['bvid'];folder=ROOT/f'data/extractions/S21/frames/{b}';out=folder/'screen_candidates.json'
 if out.exists():
  old=json.loads(out.read_text(encoding='utf-8'))
  if old.get('source_receipt_sha256')==digest(folder/'capture.json'):return old
 frames=capture.get('frames',[]);settlement=[f for f in frames if f.get('selection',{}).get('kind')!='late_numbered_speech']
 checked=[];best=None
 for f in sorted(settlement,key=lambda f:f['requested_time_ms'],reverse=True):
  v=process_frame(f,engine,names);checked.append(v)
  if v['classification_candidate']=='settlement_grid_4x3':
   if best is None or v['grid_role_candidates']+v['grid_name_candidates']>best['grid_role_candidates']+best['grid_name_candidates']:best=v
   if v['grid_role_candidates']>=9 and v['grid_name_candidates']>=10:break
 speech=next((f for f in frames if f.get('selection',{}).get('kind')=='late_numbered_speech'),None)
 result={'bvid':b,'cid':entry['cid'],'date_candidate':entry['date_candidate'],'status':'ocr_candidates_ready','source_receipt_sha256':digest(folder/'capture.json'),
  'best_settlement_frame':best,'speech_frame':speech,'frames_checked':[{'path':v['frame_path'],'classification':v['classification_candidate'],'grid_roles':v['grid_role_candidates'],'grid_names':v['grid_name_candidates']} for v in checked],
  'settlement_candidate_found':best is not None,'visual_verified':False}
 save_json(out,result);return result

def main(args):
 index=json.loads((ROOT/'data/reports/S21_文字与截图时点索引.json').read_text(encoding='utf-8'));entries=index['entries']
 if args.bvid:entries=[e for e in entries if e['bvid'] in args.bvid]
 if args.limit:entries=entries[:args.limit]
 engine=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':4,'EngineConfig.onnxruntime.inter_op_num_threads':1})
 names=known_names();state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'season':'S21','items':{}};handled=set();idle=time.monotonic()
 while True:
  cap=json.loads(CAPTURE.read_text(encoding='utf-8'));changed=False
  for e in entries:
   b=e['bvid']
   if b in handled:continue
   item=cap.get('items',{}).get(b)
   if not item or item.get('status')!='captured':continue
   try:
    r=process(e,item,engine,names);state['items'][b]={'status':r['status'],'settlement_candidate_found':r['settlement_candidate_found'],'screen_candidates':f'data/extractions/S21/frames/{b}/screen_candidates.json'}
   except Exception as error:state['items'][b]={'status':'failed','error_type':type(error).__name__}
   handled.add(b);changed=True;idle=time.monotonic();state['planned']=122;state['processed']=len(state['items']);state['settlement_candidates']=sum(v.get('settlement_candidate_found',False) for v in state['items'].values())
   state['updated_at_utc']=datetime.now(timezone.utc).isoformat();save_json(STATE,state)
   print(f"{b}: {state['items'][b]['status']}; settlement {state['settlement_candidates']}/{state['processed']}",flush=True)
  if len(handled)==len(entries) or not args.follow:break
  if cap.get('current_run',{}).get('state') in {'finished','stopped'} and not changed:break
  if time.monotonic()-idle>600:break
  time.sleep(10)
 print(json.dumps({k:v for k,v in state.items() if k!='items'},ensure_ascii=False,indent=2))

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser(description=__doc__);p.add_argument('--follow',action='store_true');p.add_argument('--limit',type=int);p.add_argument('--bvid',action='append');main(p.parse_args())