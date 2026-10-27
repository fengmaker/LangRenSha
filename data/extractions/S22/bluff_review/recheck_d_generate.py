import json,re,pathlib
ROOT=pathlib.Path('.'); WORK=ROOT/'data/extractions/S22/bluff_review'
part=json.load(open(WORK/'part_b.json',encoding='utf-8'))
dossiers=sorted((ROOT/'data/games/S22').glob('*/dossier.json'))
by_bv={}; idx_by_slug={}
for i,p in enumerate(dossiers,1):
 d=json.load(open(p,encoding='utf-8')); m=re.search(r'BV[0-9A-Za-z]{10}',d['slug'])
 if m: by_bv[m.group(0)]=(i,p,d); idx_by_slug[d['slug']]=(i,p,d)

def paths(bv):
 i,p,d=by_bv[bv]; out=[]
 for f in d.get('files',[]):
  if f.get('role') in {'subtitle','transcript'} and f.get('path') and (ROOT/f['path']).exists(): out.append(f['path'])
 out += [x.as_posix() for x in (ROOT/'data/seasons/S22').rglob(f'*{bv}*.json')]
 out += [(p.parent/'复核记录.json').as_posix(),(p.parent/'复盘原文.txt').as_posix()]
 return list(dict.fromkeys(x for x in out if (ROOT/x).is_file()))
def rows(path):
 f=ROOT/path
 if f.suffix.lower()=='.json':
  try:d=json.load(open(f,encoding='utf-8-sig'))
  except:return []
  seq=d.get('body',d.get('segments',d.get('recap_segments',[])))
  return [{'start_ms':r.get('start_ms',round(r.get('from',0)*1000)),'end_ms':r.get('end_ms',round(r.get('to',0)*1000)),'text':r.get('text',r.get('content',''))} for r in seq]
 out=[]
 for line in f.read_text(encoding='utf-8-sig').splitlines():
  m=re.match(r'\[([\d.]+)[–—-]([\d.]+)\]\s*(.*)',line)
  if m: out.append({'start_ms':round(float(m[1])*1000),'end_ms':round(float(m[2])*1000),'text':m[3]})
 return out
def find(bv,phrase,lo=0,hi=10**10):
 for path in paths(bv):
  for r in rows(path):
   if lo<=r['start_ms']<=hi and phrase in r['text']:
    return {'kind':'speech' if ('本地全文转写' in path or '.原始.json' in path) else 'recap','source_path':path,'start_ms':int(r['start_ms']),'end_ms':int(r['end_ms']),'text':phrase,'interpretation':''}
 return None
def endday(bv):
 for path in paths(bv):
  if not path.endswith('.json'): continue
  rs=rows(path); sun=None
  for r in rs:
   t=r['text'].strip(); s=r['start_ms']
   if 250000<=s<=2000000 and '天亮了' in t and len(t)<=40:
    sun=s;break
  if sun is None: continue
  for r in rs:
   if r['start_ms']<=sun or r['start_ms']-sun>5000000: continue
   if '天黑请闭眼' in r['text'] or '天黑请别' in r['text']:
    return r['end_ms']
 return None

updates={
 ('BV1jYKV6SEwK',2):('yes','预言家',1,True,'high','2号被叫到首日发言后报告“11是个金水”，对应夜间查验并建立预言家视角；物理底牌为狼人。'),
 ('BV12pNo6HEuV',9):('yes','预言家',1,True,'high','9号首日发言轮明确报告“我验了八是狼”，是本人报查杀起跳；真预言家10号在同轮对跳。'),
 ('BV12pNo6HEiz',8):('yes','通灵师',1,True,'high','8号首日本人轮次报告验6查杀并聊验人心路，构成通灵师起跳；真通灵师6号随后应对。'),
 ('BV1oNKY6zE1Z',6):('yes','预言家',1,True,'high','裁判复盘明确6号狼人上警悍跳并取得警徽，首日身份清晰。'),
 ('BV1fPKY6gEFp',5):('yes','预言家',2,False,'high','复盘明确第二天是延期竞选警长环节，紧接着确认5号悍跳狼人自爆；这是延期的首轮竞选起跳，按规则计入。'),
 ('BV1fPKY6gEFp',7):('uncertain',None,None,None,'low','复盘仅称7号狼人自爆并记载次日延期竞选，转写未能可靠归属7号首日实际发言或自爆前是否起跳；不能把计划或自爆本身当作跳信息神。'),
 ('BV1bWKY6tEri',9):('yes','通灵师',1,True,'high','复盘明确9号狼人悍跳并赢得警徽，且首日真通灵师7号被抗推。'),
 ('BV1Pxgy68EQC',9):('yes','预言家',1,True,'high','9号首日上警直接建立预言家身份与查验/警徽流，取得警徽；复盘确认其为悍跳狼人。'),
 ('BV1Nsgy6cEiG',2):('yes','通灵师',1,True,'high','2号首日本人发言明说“本局游戏我自己底牌是张通灵师牌”并报告验人；物理底牌为盗宝大师，公开获得的技能不排除身份自称。'),
 ('BV1Abgy6tEP8',9):('yes','通灵师',1,True,'high','9号在首日警下本人轮次中被叫到发言后直接说“我通灵师啊”；此前的“昨夜平安夜请警长组织发言顺序”不代表首日结束，首日仍延续到警下与放逐阶段。裁判复盘也明确其警下跳起后首日被公投出局。'),
 ('BV19Ggx6xEqE',8):('yes','预言家',1,True,'high','裁判复盘确认8号狼人悍跳并取得警徽；首日直接报验/警徽流与真预言家1号对跳。'),
 ('BV1RGgx6xEP9',5):('yes','通灵师',1,True,'medium','复盘将5号明确标为狼人并记录其报验12号平民的通灵师身份；与首日竞选阶段交叉，按首日悍跳计入。'),
 ('BV1RGgx6xEP9',6):('yes','通灵师',1,True,'high','6号首日轮次直接自称“我是通灵师”并解释被查杀；物理底牌为狼人。'),
 ('BV1iMgq6ZEWn',2):('yes','通灵师',1,True,'medium','同局5号发言以事实句复述“二号玩家给八号玩家发金水”，结合2号为狼人底牌及真通灵师5号的对跳，支持2号首日报验起跳；保留第三方转述作依据。'),
 ('BV1mE3z6XEB1',5):('yes','预言家',1,True,'high','裁判复盘明确第一天白天5号悍跳狼人并被公投出局。'),
 ('BV1h33z6tEqx',10):('yes','通灵师',1,True,'high','裁判复盘明确第一天白天10号悍跳狼人并被公投出局。'),
 ('BV13g3z6FEdh',8):('yes','通灵师',1,True,'high','8号首日本人发言报告验1号功能好人并给出警徽流，构成通灵师身份主张；即使复盘另记第二天再次悍跳，首日已经起跳。'),
}
by_game={}
for g in part['games']:
 if g['game_id'] not in idx_by_slug: continue
 i,p,d=idx_by_slug[g['game_id']]
 if not 81<=i<=100: continue
 cand=[a for a in g.get('assessments',[]) if a.get('decision') in {'yes','uncertain'}]
 if not cand: continue
 assessments=[]
 for a in cand:
  bv=g['bvid']; seat=a['seat']; decision,claimed,claim_day,first,conf,note=updates[(bv,seat)]
  ev=[dict(e) for e in a.get('evidence',[]) if all(k in e for k in ('kind','source_path','start_ms','end_ms','text','interpretation'))]
  # Replace/append targeted direct first-day transcript anchors.
  extra=[]
  if bv=='BV1jYKV6SEwK' and seat==2:
   extra=[find(bv,'2号玩家请发言',570000,580000),find(bv,'11是个金水啊',575000,580000)]
  elif bv=='BV12pNo6HEuV' and seat==9:
   extra=[find(bv,'我验了八是狼',560000,580000)]
  elif bv=='BV12pNo6HEiz' and seat==8:
   extra=[find(bv,'过了8号玩家请发言',440000,460000),find(bv,'验得六是查杀',450000,480000)]
  elif bv=='BV1fPKY6gEFp' and seat==5:
   extra=[find(bv,'第二天延期竞选警长环节',2190000,2210000),find(bv,'5号悍跳狼人自爆',2200000,2210000)]
  elif bv=='BV1fPKY6gEFp' and seat==7:
   extra=[find(bv,'7号狼人自爆',2180000,2190000),find(bv,'所有玩家发言结束退水自爆环节',1120000,1130000)]
  elif bv=='BV1Pxgy68EQC' and seat==9:
   extra=[find(bv,'我确实是预言家',1400000,1410000),find(bv,'我验的4号玩家是金水',1400000,1420000)]
  elif bv=='BV1Nsgy6cEiG' and seat==2:
   extra=[find(bv,'但其实本局游戏我自己底牌是张通灵师牌',1120000,1150000)]
  elif bv=='BV1Abgy6tEP8' and seat==9:
   extra=[find(bv,'9号大请发言',1940000,1950000),find(bv,'我通灵师啊',1940000,1960000)]
  elif bv=='BV1RGgx6xEP9' and seat==6:
   extra=[find(bv,'因为我是通灵师虽然我被查杀到了',1100000,1120000)]
  elif bv=='BV13g3z6FEdh' and seat==8:
   extra=[find(bv,'8号玩家请发言',1060000,1080000),find(bv,'验了一号是一张有功能的好人牌',1060000,1080000),find(bv,'警徽流',1080000,1090000)]
  extra=[e for e in extra if e]
  for e in extra:
   e['interpretation']=note
   if not any((x['source_path'],x['start_ms'],x['text'])==(e['source_path'],e['start_ms'],e['text']) for x in ev): ev.append(e)
  questions=[]
  if decision=='uncertain':
   questions=['首日首轮发言窗口约390,000–1,126,580ms：复盘只确认#7狼人自爆；现有转写缺少可靠的#7座位发言标注，需核对该窗口#7是否本人实际说出预言家/通灵师身份，不能把自爆或可能的计划当作起跳。']
  assessments.append({'seat':seat,'name':a['name'],'physical_role':a['physical_role'],'decision':decision,'claimed_role':claimed,'claim_day':claim_day,'first_day_claim':first,'confidence':conf,'evidence':ev,'review_questions':questions,'decision_note':note})
 key=(i,bv)
 by_game[key]={'game_id':g['game_id'],'bvid':bv,'first_day_end_ms':endday(bv),'assessments':assessments}

games=[v for _,v in sorted(by_game.items())]
for game in games:
 if game['bvid']=='BV1Abgy6tEP8':
  for assessment in game['assessments']:
   if assessment['seat']==9:
    assessment['visual_checks']=[{'path':'data/extractions/S22/bluff_review/video_recheck/BV1Abgy6tEP8_01949.000.png','time_ms':1949000,'observation':'视频顶部明确显示“正赛第三局 第一天”，当前发言者为9号荣耀；结合字幕“我通灵师啊”，确认为首日警下本人发言。'}]
payload={'schema_version':1,'scope':'first_day','games':games}
tmp=WORK/'recheck_d.json.tmp'; tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(WORK/'recheck_d.json')
print('wrote',len(games),'games',sum(len(g['assessments']) for g in games),'assessments')
