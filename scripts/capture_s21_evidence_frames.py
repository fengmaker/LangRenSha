"""Resumable S21 settlement/speech frame evidence; never import game facts."""
from __future__ import annotations
import argparse,hashlib,json,threading,time,sys
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from fractions import Fraction
from pathlib import Path
import av
from collect_bilibili_audio import Collector,CollectionError,save_json
ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'data/indexes/S21_采集计划.json'
INDEX=ROOT/'data/reports/S21/S21_文字与截图时点索引.json'
STATE=ROOT/'data/reports/S21/S21_截图采集进度.json'
STOP=threading.Event();LOCK=threading.Lock();PREVIOUS=0.0

def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def relative(p):return p.relative_to(ROOT).as_posix()
def api(client,path,params):
 global PREVIOUS
 if STOP.is_set():raise RuntimeError('batch_stopped')
 with LOCK:
  delay=1.3-(time.monotonic()-PREVIOUS)
  if delay>0:time.sleep(delay)
  PREVIOUS=time.monotonic()
 try:return client.api(path,params)
 except CollectionError as e:
  if any(s in str(e) for s in ['HTTP 403','HTTP 429','HTTP 412','业务状态 -412','业务状态 -352','业务状态 -799']):STOP.set()
  raise

def selected_candidates(entry,max_settlement=6):
 candidates=[c for c in entry.get('frame_candidates',[]) if c.get('within_media_duration',True) and 0<=c.get('time_ms',-1)<entry['duration_ms']-1000]
 def rank(c):
  k=c['kind'];p=6
  if '-1000' in k:p=0
  elif '-3000' in k:p=1
  elif '-5000' in k:p=2
  elif 'during' in k or 'tail' in k:p=3
  elif k.endswith('recap_end') or k.endswith('game_end_cue'):p=4
  elif '+3000' in k:p=5
  elif '+6000' in k or '+12000' in k:p=9
  return p,-c['time_ms']
 chosen=[]
 for c in sorted(candidates,key=rank):
  if not c['kind'].startswith('settlement'):continue
  if any(abs(c['time_ms']-x['time_ms'])<1800 for x in chosen):continue
  chosen.append(c)
  if len(chosen)>=max_settlement:break
 speech=entry.get('last_game_day_speech_command')
 if speech:
  ms=min(speech['end_ms']+8000,entry['duration_ms']-2000)
  chosen.append({'kind':'late_numbered_speech','time_ms':ms,'reason':'最晚明确座位发言口令后8秒；待目视核对实际游戏日及图层',
   'source_segment_indices':[speech['source_segment_index']],'within_media_duration':True})
 return sorted(chosen,key=lambda c:c['time_ms'])

def collect(entry,original,cookies,max_settlement):
 b=entry['bvid'];folder=ROOT/'data/extractions/S21/frames'/b;folder.mkdir(parents=True,exist_ok=True)
 receipt_path=folder/'capture.json';previous=json.loads(receipt_path.read_text(encoding='utf-8')) if receipt_path.exists() else {}
 requested=selected_candidates(entry,max_settlement)
 source=ROOT/entry['selected_source_path'];source_sha=digest(source)
 assert source_sha==entry['source_hashes']['selected_source_sha256']
 manifest=ROOT/f'data/raw/bilibili/{b}/p{entry["page"]:02d}/manifest.json';media=json.loads(manifest.read_text(encoding='utf-8'))
 assert media['bvid']==b and media['cid']==entry['cid']==original['cid'] and str(media['owner']['mid'])=='19106800'
 result={'bvid':b,'cid':entry['cid'],'page':entry['page'],'date_candidate':entry['date_candidate'],'title':entry['title'],
  'source_manifest':relative(manifest),'source_manifest_sha256':digest(manifest),'text_source':relative(source),'text_source_sha256':source_sha,
  'status':'captured','visual_verified':False,'frame_selection_note':'时点来自文字候选，截图是否结算页及图层含义仍待逐张核对','frames':[]}
 if not requested:result['status']='needs_manual_timing';save_json(receipt_path,result);return result
 existing={r['requested_time_ms']:r for r in previous.get('frames',[]) if r.get('frame_path') and (ROOT/r['frame_path']).is_file() and digest(ROOT/r['frame_path'])==r.get('frame_sha256')}
 missing=[]
 for c in requested:
  if c['time_ms'] in existing:result['frames'].append({**existing[c['time_ms']],'selection':c})
  else:missing.append(c)
 if missing:
  if STOP.is_set():result['status']='pending_stopped';return result
  client=Collector('cookies',cookies,quiet=True)
  play=api(client,'/x/player/playurl',{'bvid':b,'cid':entry['cid'],'fnval':16,'fnver':0,'qn':80})['data']
  tracks=[t for t in play.get('dash',{}).get('video',[]) if t.get('baseUrl') or t.get('base_url')]
  if not tracks:raise ValueError('独立视频流不可用')
  limited=[t for t in tracks if int(t.get('height',0))<=1080] or tracks
  chosen=max(limited,key=lambda t:(int(t.get('height',0)),str(t.get('codecs','')).startswith('avc')))
  result['stream_format']={k:chosen.get(k) for k in ['id','codecs','width','height']}
  url=chosen.get('baseUrl') or chosen['base_url']
  with av.open(url,options={'headers':'Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n','rw_timeout':'20000000'}) as video:
   stream=video.streams.video[0]
   for c in missing:
    if STOP.is_set():result['status']='pending_stopped';break
    second=c['time_ms']/1000;path=folder/f'{b}_{second:09.3f}.png'
    # Keep earlier inspected bytes. Legacy pilot frames lack exact decoded PTS metadata.
    if path.exists():
     from PIL import Image
     with Image.open(path) as im:width,height=im.size
     result['frames'].append({'requested_time_ms':c['time_ms'],'actual_frame_time_ms':None,'frame_path':relative(path),'frame_sha256':digest(path),
      'width':width,'height':height,'timestamp_note':'复用先前按同一目标截得的原帧，既有工具未保存实际PTS','selection':c,'visual_verified':False});continue
    video.seek(int(Fraction(str(second))/stream.time_base),stream=stream,backward=True)
    for frame in video.decode(stream):
     if frame.time is not None and frame.time>=second:
      image_frame=frame.reformat(format='rgb24');image_frame.pts=0;image_frame.time_base=Fraction(1,1)
      with av.open(str(path),mode='w',format='image2') as output:
       encoder=output.add_stream('png',rate=1);encoder.width,encoder.height,encoder.pix_fmt=frame.width,frame.height,'rgb24'
       for packet in encoder.encode(image_frame):output.mux(packet)
       for packet in encoder.encode(None):output.mux(packet)
      result['frames'].append({'requested_time_ms':c['time_ms'],'actual_frame_time_ms':round(frame.time*1000),'frame_path':relative(path),
       'frame_sha256':digest(path),'width':frame.width,'height':frame.height,'selection':c,'visual_verified':False})
      save_json(receipt_path,{**result,'status':'partial'})
      break
    else:raise ValueError('候选时点没有可解码视频帧')
 result['frames'].sort(key=lambda f:f['requested_time_ms']);result['captured_at_utc']=datetime.now(timezone.utc).isoformat()
 result['captured_frame_count']=len(result['frames']);save_json(receipt_path,result);return result

def run(args):
 frozen=json.loads(PLAN.read_text(encoding='utf-8'));allowed={e['bvid']:e for e in frozen['entries'] if e['labels']['phase_candidate'] in {'regular','finals_week'}}
 index=json.loads(args.index.read_text(encoding='utf-8'));entries=[e for e in index['entries'] if e['bvid'] in allowed]
 if args.bvid:entries=[e for e in entries if e['bvid'] in args.bvid]
 if args.limit:entries=entries[:args.limit]
 state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'season':'S21','items':{}}
 state.update({'planned_included_media':len(allowed),'available_timing_entries':len(index['entries']),'excluded_local_only':len(frozen['entries'])-len(allowed),
  'scope_note':'用户排除12条表演赛与3条特辑；仅抓取112条正赛与10条决赛候选帧。','current_run':{'state':'running','entries':len(entries)}})
 with ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures={pool.submit(collect,e,allowed[e['bvid']],args.cookies_file,args.max_settlement):e for e in entries}
  for future in as_completed(futures):
   e=futures[future]
   try:r=future.result()
   except Exception as error:
    if any(s in str(error) for s in ['403','429','412']):STOP.set()
    r={'bvid':e['bvid'],'cid':e['cid'],'status':'failed','error_type':type(error).__name__,'reason':str(error) if isinstance(error,(ValueError,AssertionError)) and 'http' not in str(error).lower() else '取帧失败，未记录可能含临时签名地址的异常详情'}
   state['items'][e['bvid']]=r;state['updated_at_utc']=datetime.now(timezone.utc).isoformat()
   state['captured_media']=sum(x.get('status')=='captured' for x in state['items'].values());state['captured_frames']=sum(len(x.get('frames',[])) for x in state['items'].values())
   save_json(STATE,state);print(f"{e['bvid']}: {r['status']} {len(r.get('frames',[]))} frames; {state['captured_media']}/{len(allowed)} sources",flush=True)
 state['current_run']['state']='stopped' if STOP.is_set() else 'finished';save_json(STATE,state)
 return {k:v for k,v in state.items() if k!='items'}

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',type=Path,default=INDEX);p.add_argument('--cookies-file',type=Path,default=ROOT/'.secrets/bilibili.cookies.txt')
 p.add_argument('--workers',type=int,choices=[1,2],default=2);p.add_argument('--max-settlement',type=int,default=6);p.add_argument('--limit',type=int);p.add_argument('--bvid',action='append')
 args=p.parse_args();print(json.dumps(run(args),ensure_ascii=False,indent=2))