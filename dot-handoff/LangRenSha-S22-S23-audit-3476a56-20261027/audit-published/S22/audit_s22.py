import subprocess,json,hashlib,re,csv,collections
from pathlib import Path
R=Path('/workspace/scratch/a7edd912716e/langrensha-cloud'); O=Path('/workspace/scratch/a7edd912716e/audit-published/S22'); REF='3476a56af155f36a0d0050abc1660ed0d6fd538a'
registry={}; cache={}
def read(p,required=True):
 if p in cache:return cache[p]
 q=subprocess.run(['git','show',REF+':'+p],cwd=R,capture_output=True)
 if q.returncode:
  if required:print('MISSING',p)
  return None
 b=q.stdout;registry[p]={'path':p,'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'bytes':len(b)}
 a=json.loads(b) if p.endswith('.json') else b.decode('utf-8-sig');cache[p]=a;return a
paths=subprocess.check_output(['git','-c','core.quotePath=false','ls-tree','-r','--name-only',REF,'data/games/S22'],cwd=R,text=True).splitlines()
games=[];anomalies=[];quotes=[];evidence_meta=[]
rules=read('config/S22_formal_rules.json');confirm_paths=[p for p in subprocess.check_output(['git','-c','core.quotePath=false','ls-tree','-r','--name-only',REF,'data/extractions/S22'],cwd=R,text=True).splitlines() if '用户确认_' in p]
for p in confirm_paths:read(p)
for p in ['data/reports/S22_逐项因果复核.json','data/reports/S22_技能结算补充复核.json','data/extractions/S22/endgame_reviewed_sources.json','data/reports/S22_拍刀交叉复核.json','data/reports/S22_日序与阵营更正.json','data/reports/S22_投票逐局核对.json']:read(p)
def issue(g,code,path,old,candidate,note,level='source_internal_candidate'):
 a={'game_id':g['game_id'],'date':g['date'],'code':code,'field':path,'old_value':old,'candidate_value':candidate,'conclusion':level,'note':note};anomalies.append(a);g['findings'].append(a)
def num(s):
 if s.isdigit():return int(s)
 return {'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}.get(s)
N=r'(?:1[012]|[1-9]|十二|十一|十|[一二两三四五六七八九])'
vp=re.compile(r'(?<![\d一二三四五六七八九十])('+N+r')\s*号?\s*(?:玩家)?\s*(?:投给|投向|投了|投)\s*('+N+r')\s*号?')
ap=re.compile(r'(?<![\d一二三四五六七八九十])('+N+r')\s*号?\s*(?:玩家)?\s*弃票')
for dp in sorted(p for p in paths if p.endswith('/dossier.json')):
 base=dp.rsplit('/',1)[0];d=read(dp);v=read(base+'/voting.json');en=read(base+'/endgame.json');vr=read(base+'/voting_review.json');bvid=re.search(r'BV\w+',d['slug']).group(0);ep='data/extractions/S22/voting/'+bvid+'.json';ex=read(ep);rp=base+'/复核记录.json';rec=read(rp,False);rt=read(base+'/复盘原文.txt',False)
 source=ex.get('source_path') if ex else rec.get('source_path') if rec else None
 src=read(source,False) if source else None
 g={'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d.get('game_number'),'board':d['board'],'winner':d['winner'],'base_path':base,'sources':{},'scope':['12座姓名与底牌/个人阵营','各票轮票权/逐人票向/结果','逐夜行动/日夜死亡与时序','特殊状态/终局','网站统计的源输入'],'findings':[],'source_internal_checks':{},'evidence_coverage':{'formal_dossier':True,'voting_extraction':bool(ex),'recap_text':bool(rt),'recap_locator':base+'/复盘定位.json' in paths,'review_record':bool(rec),'primary_text_readable':src is not None,'direct_audio_video_review_this_audit':False},'field_counts':{'seats':len(d['seats']),'rounds':len(d['rounds']),'ballots':len(v['ballots']),'votes':sum(len(b['votes']) for b in v['ballots'])},'preserved_unknowns':{},'user_confirmations':confirm_paths,'derived_results':[]}
 for p in [dp,base+'/voting.json',base+'/endgame.json',base+'/voting_review.json',ep,rp,base+'/复盘原文.txt',source]:
  if p in registry:g['sources'][p]=registry[p]
 if source in registry:
  match=registry[source]['sha256']==ex.get('source_sha256');g['source_internal_checks']['extraction_source_sha_matches_current_source']=match
  if not match:issue(g,'source_hash_mismatch','extraction.source_sha256',ex.get('source_sha256'),registry[source]['sha256'],'指向文本版本与当前源字节不同；不自动否定旧结论。','provenance_gap')
 g['source_internal_checks']['voting_equals_extracted_facts']=ex.get('facts')==v
 if ex.get('facts')!=v:issue(g,'formal_voting_differs_extraction','voting',None,None,'正式票型与提取facts不同，需确认是否存在后续补丁。')
 g['source_internal_checks']['seat_numbers_1_to_12']=sorted(s['seat'] for s in d['seats'])==list(range(1,13))
 roles=collections.Counter(s['role'] for s in d['seats']);board=rules['boards'][d['board']];comp=board['role_composition'];factions={x['physical_identity']:x.get('victory_faction') for x in (comp if isinstance(comp,list) else board.get('role_pool',[]))}
 if isinstance(comp,list):
  expected={x['physical_identity']:x['count'] for x in comp};g['source_internal_checks']['role_composition']=roles==expected
  if roles!=expected:issue(g,'role_composition','seats.role',dict(roles),expected,'仅规则组成差异，不据此改底牌。')
 seats={s['seat']:s for s in d['seats']}
 for s in d['seats']:
  exp=factions.get(s['role'])
  if exp in ['good','werewolf'] and s['faction'] not in [exp,'unknown',None]:issue(g,'faction_mismatch',f"seats[{s['seat']}].faction",s['faction'],exp,'底牌与本季已确认个人阵营规则不符。')
 for rr in d['rounds']:
  for ph in ['night','day']:
   for e in rr[ph]:
    if e['slot']=='mixed_blood_model' and e['action']=='choose' and len(e['targets'])==1:
     actor=e['actor'];tar=e['targets'][0]
     if actor in seats and tar in seats and seats[actor]['faction']!=seats[tar]['faction']:issue(g,'mixed_faction',f"seats[{actor}].faction",seats[actor]['faction'],seats[tar]['faction'],f'混血榜样为{tar}，按已确认规则阵营跟随榜样；待核是否特殊状态。')
 g['preserved_unknowns']['seat_roles']=[s['seat'] for s in d['seats'] if not s.get('role') or s['role']=='未知']
 g['preserved_unknowns']['factions']=[s['seat'] for s in d['seats'] if s.get('faction') not in ['good','werewolf']]
 g['preserved_unknowns']['event_action_unknown']=sum(e.get('action')=='unknown' for rr in d['rounds'] for ph in ['night','day'] for e in rr[ph])
 for reg in v['registrations']:
  a=reg.get('on_police');b=reg.get('off_police')
  if a is not None and b is not None and (set(a)&set(b) or set(a)|set(b)!=set(range(1,13))):issue(g,'registration_partition','registrations.'+reg['id'],reg,None,'首次报名分组有交集或缺员；可能不完整登记，不能补造。')
 for b in v['ballots']:
  voter=[x['voter'] for x in b['votes']];eligible=b.get('eligible_voters');prefix='ballots.'+b['id']
  if len(set(voter))!=len(voter):issue(g,'duplicate_voter',prefix,voter,None,'同一轮重复投票人。')
  if eligible is not None and set(voter)!=set(eligible):issue(g,'eligible_vote_set_mismatch',prefix+'.eligible_voters',eligible,voter,'实录票与票权不一致；先查未记录名单，不自动默认弃票。')
  counts=collections.Counter(x['target'] for x in b['votes'] if x['state']=='cast');maxvotes=max(counts.values()) if counts else 0;tops=sorted(k for k,n in counts.items() if n==maxvotes)
  g['derived_results'].append({'ballot_id':b['id'],'day':b['day'],'kind':b['kind'],'unweighted_counts':dict(counts),'recorded_winner':b.get('winner'),'top_seats_unweighted':tops,'note':'S22归档不计半票；算术仅作旁检，不能替代现场胜出。'})
  if b.get('winner') and b['winner'] not in tops:issue(g,'winner_not_unweighted_top',prefix+'.winner',b['winner'],tops,'仅不加权票数候选，警徽半票或技能重投等需对源，不是已认定事实错误。')
  evid=(ex or {}).get('evidence',{}).get(b['id'],[])
  allparsed={}; conflicts=[]
  for ev in evid:
   q=ev.get('quote','');parts=re.split(r'(?:请出票|请出示|开始投票)',q);t=parts[-1] if len(parts)>1 else q
   # keep announcement section, avoiding aftermath discussion when possible
   t=re.split(r'投票结束',t)[0]
   for m in vp.finditer(t):
    aa,bb=map(num,m.groups())
    if aa in allparsed and allparsed[aa]!=bb:conflicts.append(aa)
    allparsed[aa]=bb
   for m in ap.finditer(t):
    aa=num(m.group(1));allparsed[aa]=None
   em={'game_id':g['game_id'],'ballot_id':b['id'],'path':ev.get('path'),'start_ms':ev.get('start_ms'),'end_ms':ev.get('end_ms'),'quote':q,'evidence_container':ep,'evidence_container_sha256':registry[ep]['sha256']};quotes.append(em)
  observed={x['voter']:x['target'] if x['state']=='cast' else None for x in b['votes']}
  parsed_ok={k:vv for k,vv in allparsed.items() if k in observed and k not in conflicts}
  for k,t in parsed_ok.items():
   if observed[k]!=t:issue(g,'rollcall_text_differs_vote',prefix+f'.votes[{k}]',observed[k],t,'连续唱票旁证中的显式票向与正式票不同；需人工读上下文/后续确认。')
  g.setdefault('ballot_evidence_checks',[]).append({'ballot_id':b['id'],'day':b['day'],'kind':b['kind'],'vote_count':len(b['votes']),'eligible_count':len(eligible) if eligible is not None else None,'evidence_span_count':len(evid),'explicit_rollcall_pairs_parsed':len(parsed_ok),'matching_pairs':sum(observed[k]==vv for k,vv in parsed_ok.items()),'not_explicitly_parsed_voters':[k for k in observed if k not in parsed_ok],'parsing_limit':'regex candidate check only; ASR/reference/number ambiguity must be reviewed, and rule-derived abstentions are not raw rollcall evidence'})
 # report linkage, not independent validation
 g['existing_causal_decisions']=[{'question_id':x.get('question_id'),'conclusion':x.get('conclusion'),'method':x.get('method'),'confidence':x.get('confidence')} for x in ex.get('causal_review',{}).get('decisions',[])]
 g['terminal']=ex.get('game_flow',{}).get('terminal');g['existing_rule_applications']=ex.get('rule_applications',[])
 games.append(g)
 print(len(games),bvid,'issues',len(g['findings']),flush=True)
 if len(games)%10==0:
  (O/'audit_progress.json').write_text(json.dumps({'games':games,'anomalies':anomalies},ensure_ascii=False,indent=2))
(O/'per_game_audit.json').write_text(json.dumps({'baseline':REF,'method':'read-only source/internal and textual-evidence audit; not primary media verification','games':games},ensure_ascii=False,indent=2))
(O/'candidate_anomalies.json').write_text(json.dumps(anomalies,ensure_ascii=False,indent=2))
(O/'ballot_evidence.json').write_text(json.dumps(quotes,ensure_ascii=False,indent=2))
(O/'evidence_registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2))
# data bundle excludes full sources, contains formal/extraction data for targeted review
bundle={g['bvid']:{'dossier':cache[g['base_path']+'/dossier.json'],'voting':cache[g['base_path']+'/voting.json'],'endgame':cache[g['base_path']+'/endgame.json'],'extraction':cache['data/extractions/S22/voting/'+g['bvid']+'.json'],'review_record':cache.get(g['base_path']+'/复核记录.json'),'recap':cache.get(g['base_path']+'/复盘原文.txt')} for g in games}
(O/'review_bundle.json').write_text(json.dumps(bundle,ensure_ascii=False))
print('SUMMARY',len(games),len(anomalies),collections.Counter(x['code'] for x in anomalies))
