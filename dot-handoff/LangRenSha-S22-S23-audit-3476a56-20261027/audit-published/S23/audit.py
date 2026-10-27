import pathlib,json,hashlib,re,collections,copy,csv
BASE=pathlib.Path('/workspace/scratch/a7edd912716e/audit-published/S23');E=BASE/'evidence';REF='3476a56af155f36a0d0050abc1660ed0d6fd538a'
def read(p):return json.loads((E/p).read_text())
def sha(p):return hashlib.sha256((E/p).read_bytes()).hexdigest()
def evs(d):return {(r['number'],ph,e['slot']):e for r in d['rounds'] for ph in ['night','day'] for e in r[ph]}
def segments(v):
 out=[]
 for i,row in enumerate(v.get('segments',v.get('body',[]))):
  if 'start_ms' in row:a,b,t=row['start_ms'],row['end_ms'],row.get('text','')
  elif 'start' in row:a,b,t=round(row['start']*1000),round(row['end']*1000),row.get('text','')
  else:a,b,t=round(row['from']*1000),round(row['to']*1000),row.get('content','')
  if t.strip():out.append({'index':i,'start_ms':a,'end_ms':b,'text':t})
 return out
def norm(s):return re.sub(r'\s+','',str(s))
def walk(x,loc=''):
 if isinstance(x,dict):
  if x.get('source_path') and (x.get('quote') or x.get('text')):yield loc,x
  for k,v in x.items():yield from walk(v,loc+'/'+k)
 elif isinstance(x,list):
  for i,v in enumerate(x):yield from walk(v,loc+'/'+str(i))
def compact(e):return {k:e.get(k) for k in ['action','actor','targets','result','effects'] if e.get(k) is not None}
manifest={x['path']:x for x in read_manifest} if False else {}
manifest={x['path']:x for x in json.loads((BASE/'evidence_manifest.json').read_text())+json.loads((BASE/'source_manifest.json').read_text())}
bluff=read('website/assets/bluffs/S23.json');bg={g['bvid']:g for g in bluff['games']};parts=collections.defaultdict(list)
for p in sorted((E/'data/extractions/S23/bluff_review/parts').glob('audit_?.json')):
 for g in json.loads(p.read_text())['games']:parts[g['bvid']].append({'path':str(p.relative_to(E)),'game':g})
records=[]; anomalies=[];recapdocs=[]
WOLVES={'狼人','机械狼','狼王','黑狼王','假面','诡术师','典狱长','盗宝大师','九尾狐','狼术师'}
for fp in sorted((E/'data/games/S23').glob('*/dossier.json')):
 folder=fp.parent.relative_to(E);d=read(folder/'dossier.json');bvid=folder.name.rsplit('_',1)[1];f='data/extractions/S23/game_reviews/'+bvid
 entry=read(f+'/entry.json');daily=read(f+'/daily_audit.json');ai=read(f+'/ai_review.json');rv=read(f+'/dossier.reviewed.json');baseline=read(f+'/baseline.dossier.json');pri=read(f+'/primary_review.json') if (E/f/'primary_review.json').exists() else {}
 v=read(folder/'voting.json');cand=read(folder/'dossier.candidate.json');context=read(folder/'formal_context.json');end=read(folder/'endgame.json');supp=read(folder/'supplemental.json');vc=read(folder/'vote_control.json');raw=read(entry['source_path']);rows=segments(raw);alltext=norm(''.join(x['text'] for x in rows));w=daily['recap_window'];recap=[x for x in rows if x['end_ms']>w['start_ms'] and x['start_ms']<w['end_ms']]
 source_hash=sha(entry['source_path']);ee=evs(d);be=evs(baseline);ce=evs(cand);fields=[];checks=[];issues=[]
 def issue(code,**kw):
  x={'bvid':bvid,'game_id':d['slug'],'date':d['date'],'game_number':d['game_number'],'code':code,**kw};issues.append(x);anomalies.append(x)
 def field(path,old,current,evidence,conclusion='retained_no_change_proposed',level='source_internal_and_prior_review_crosscheck'):
  fields.append({'field':path,'baseline_old_value':old,'formal_current_value':current,'candidate_value':current,'evidence':evidence,'conclusion':conclusion,'evidence_level':level})
 # Binding: transcript bytes and current audit source identity.
 for title,x in [('entry',entry),('ai_review',ai),('daily_audit',daily)]:
  ok=x.get('source_sha256')==source_hash;checks.append({'kind':'source_hash_binding','document':title,'matches':ok})
  if not ok:issue('source_hash_binding_mismatch',document=title,expected=x.get('source_sha256'),actual=source_hash)
 # Record all fixed seat facts with their explicit prior review anchors, without declaring pixel verification.
 baseline_seats={x['seat']:x for x in baseline['seats']};review_seats={x['seat']:x for x in rv['seats']}
 for s in d['seats']:
  anchors=[{'path':f+'/ai_review.json','locator':f'/decisions/{i}','sha256':sha(f+'/ai_review.json'),'reasoning':q.get('reasoning'),'source_evidence':q.get('evidence',[])} for i,q in enumerate(ai.get('decisions',[])) if str(q.get('field','')).startswith('seats')]
  for k in ['name','role','faction','learning_target','learned_role']:
   field(f'seats[{s["seat"]}].{k}',baseline_seats.get(s['seat'],{}).get(k),s.get(k),anchors)
  if s['role'] in WOLVES and s['faction']!='werewolf':issue('fixed_wolf_faction_conflict',seat=s['seat'],formal=s)
  if s['role'] not in WOLVES|{'混血儿'} and s['faction']!='good':issue('fixed_good_faction_conflict',seat=s['seat'],formal=s)
  if s['role']!=review_seats[s['seat']]['role']:issue('reviewed_role_diff',seat=s['seat'],old=review_seats[s['seat']]['role'],current=s['role'])
 # Mixed blood factual idol and individual victory faction, separate from physical identity.
 seats={s['seat']:s for s in d['seats']}
 for key,e in ee.items():
  if e['slot']=='mixed_blood_model' and e.get('action')=='choose' and len(e.get('targets',[]))==1:
   a=e['actor'];t=e['targets'][0]
   if a in seats and t in seats and seats[a]['faction']!=seats[t]['faction']:issue('mixed_blood_faction_conflict',actor=a,target=t,formal_faction=seats[a]['faction'],target_faction=seats[t]['faction'])
 # Prior ai winner decision and final recap are separate evidence sources.
 win=[{'path':f+'/ai_review.json','locator':'/decisions/'+str(i),'sha256':sha(f+'/ai_review.json'),'source_evidence':q.get('evidence',[])} for i,q in enumerate(ai.get('decisions',[])) if q.get('field')=='winner']
 field('winner',baseline.get('winner'),d['winner'],win)
 for q in ai.get('decisions',[]):
  if q.get('field')=='winner' and q.get('after')!=d['winner']:issue('review_winner_diff',old=q.get('after'),current=d['winner'])
 # Semantic event records cover every stored slot; unknowns remain unknown.
 for key,e in ee.items():
  n,ph,slot=key;anchors=[]
  for i,p in enumerate(daily.get('event_patches',[])):
   if (p['round'],p['phase'],p['slot'])==key:anchors.append({'path':f+'/daily_audit.json','locator':f'/event_patches/{i}','sha256':sha(f+'/daily_audit.json'),'changes':p['changes']})
  for i,q in enumerate(ai.get('decisions',[])):
   if q.get('field')==f'rounds[{n}].{ph}.{slot}':anchors.append({'path':f+'/ai_review.json','locator':f'/decisions/{i}','sha256':sha(f+'/ai_review.json'),'source_evidence':q.get('evidence',[])})
  field(f'rounds[{n}].{ph}.{slot}',compact(be[key]) if key in be else None,compact(e),anchors or [{'path':f+'/daily_audit.json','locator':'/checks','sha256':sha(f+'/daily_audit.json')},{'path':entry['source_path'],'sha256':source_hash,**w}],conclusion='unknown_preserved' if e['action']=='unknown' else 'retained_no_change_proposed',level='unknown_not_fact_verified' if e['action']=='unknown' else 'source_internal_and_prior_review_crosscheck')
 # Every explicitly applied latest patch should survive into formal; allowed normalizations are in context.
 for i,p in enumerate(daily.get('event_patches',[])):
  key=(p['round'],p['phase'],p['slot']);actual=ee.get(key,{})
  for k,val in p['changes'].items():
   if actual.get(k)!=val:
    normed=any(t.get('round')==p['round'] and t.get('phase')==p['phase'] and t.get('slot')==p['slot'] for t in context['normalization']['explicit_transformations'])
    extension_preserved=any((t.get('round'),t.get('phase'),t.get('slot'))==key and t.get('fields',{}).get(k)==val for t in context['normalization']['source_event_extensions'])
    if extension_preserved:checks.append({'kind':'daily_patch_metadata_preserved_in_formal_context','round':key[0],'phase':key[1],'slot':key[2],'field':k,'value':val})
    if not normed and not extension_preserved:issue('daily_patch_formal_diff',field=str(key)+'.'+k,patch_value=val,formal_value=actual.get(k),locator=f+'/daily_audit.json#/event_patches/'+str(i))
 # Source subtitle quote verification: exact text and timestamp window, including latest bluff parts.
 proof=[]
 docs=[(f+'/ai_review.json',ai),(f+'/daily_audit.json',daily),(f+'/primary_review.json',pri)]+[(p['path'],p['game']) for p in parts[bvid]]
 for path,obj in docs:
  for loc,q in walk(obj):
   sp=q['source_path'];text=q.get('quote',q.get('text',''));kind='unread_media_or_other_source';valid=None;fullvalid=None;actual_sha=None
   if sp==entry['source_path']:
    kind='archived_transcript';actual_sha=source_hash;a=q.get('start_ms');b=q.get('end_ms');selection=[r for r in rows if a is not None and b is not None and r['end_ms']>=a-2 and r['start_ms']<=b+2]
    valid=norm(text) in norm(''.join(r['text'] for r in selection)) if a is not None and b is not None else None;fullvalid=norm(text) in alltext
   elif (E/sp).exists() and pathlib.Path(sp).suffix in ['.txt','.json']:
    kind='archived_text';actual_sha=sha(sp);fullvalid=norm(text) in norm((E/sp).read_text());valid=fullvalid
   proof.append({'document':path,'locator':loc,'source_path':sp,'source_sha256_recorded':q.get('source_sha256'),'source_sha256_actual':actual_sha,'hash_matches':q.get('source_sha256')==actual_sha if actual_sha and q.get('source_sha256') else None,'start_ms':q.get('start_ms'),'end_ms':q.get('end_ms'),'kind':kind,'quote_matches_window':valid,'quote_matches_full_text':fullvalid,'quote':text})
 # Latest ballot payload checked separately from source facts. Formal equality is not media verification.
 for b in v['ballots']:field('voting.'+b['id'],None,b,[{'path':f+'/daily_audit.json','locator':'/voting_replacement' if 'voting_replacement' in daily else '/finding_resolutions','sha256':sha(f+'/daily_audit.json')},{'path':f+'/voting.reviewed.json','sha256':sha(f+'/voting.reviewed.json')}])
 if daily.get('voting_replacement'):
  for b in daily['voting_replacement']['ballots']:
   now=next((x for x in v['ballots'] if x['id']==b['id']),None)
   if now!=b:issue('voting_replacement_diff',ballot=b['id'],old=b,current=now)
 # Conservative chronology: not apply post-vote shot before vote; sheriff night-death exception explicit.
 dead=set();survival=[];shots=collections.Counter()
 for rr in d['rounds']:
  n=rr['number'];prior=set(dead);nd={t for e in rr['day'] if e['slot']=='night_deaths' and e['action'] in ['die','deaths'] for t in e['targets']}
  for b in [b for b in v['ballots'] if b['day']==n]:
   excluded=prior|(nd if b['kind']=='exile' else set());voters={x['voter'] for x in b['votes']};eligible=set(b.get('eligible_voters') or [])
   check={'ballot':b['id'],'day':n,'kind':b['kind'],'known_prior_dead':sorted(prior),'night_dead':sorted(nd),'dead_voters':sorted(excluded&voters),'dead_eligible':sorted(excluded&eligible),'voters_outside_eligible':sorted(voters-eligible) if b.get('eligible_voters') is not None else None}
   survival.append(check)
   if check['dead_voters'] or check['dead_eligible'] or check['voters_outside_eligible']:issue('vote_survival_conflict',detail=check)
   counts=collections.Counter(x['target'] for x in b['votes'] if x['state']=='cast' and x['target'] is not None)
   if b['winner'] is not None and counts and counts[b['winner']]<max(counts.values())-0.5:issue('ballot_winner_not_highest_even_half_vote',ballot=b['id'],winner=b['winner'],counts=dict(counts))
  dead.update(nd)
  for e in rr['day']:
   if e['action']=='self_destruct' and e.get('actor'):dead.add(e['actor'])
   if e['slot'] in ['exile_result','second_exile_result'] and e['action']=='exile':dead.update(e['targets'])
   if e['action']=='shoot':dead.update(e['targets']);shots[e.get('actor')]+=1
  for x in supp['events']:
   if x['round']==n and x['event']['action'] in ['dq','DQ']:dead.update(x['event'].get('targets',[]) or [x['event'].get('actor')])
 # User-confirmed special policies.
 if d['board']=='treasure_master':
  e=ee.get((1,'night','wolf_attack'),{})
  if e.get('action')!='forbidden' or e.get('targets'):issue('treasure_first_night_confirmed_rule_conflict',current=e)
 if d['board']=='masquerade':
  for key,e in ee.items():
   if key[0]==1 and key[1]=='night' and e['slot'] in ['mask_check','mask_put','dancer_action'] and e['action'] not in ['unknown','unavailable','pass']:issue('masquerade_first_night_confirmed_rule_conflict',current=e)
 # Published wolf seats and final explicit user decision.
 bluffchecks=[]
 for a in bg[bvid]['assessments']:
  s=seats[a['seat']];ok=a['physical_role']==s['role'] and s['role'] in WOLVES and a['name']==s['name'];bluffchecks.append({'seat':a['seat'],'decision':a['decision'],'claim_day':a.get('claim_day'),'role_name_match':ok,'verification_status':a.get('verification_status'),'requires_user_review':a.get('requires_user_review')})
  if not ok:issue('bluff_seat_identity_mismatch',assessment=a,seat_record=s)
  if a['decision'] not in ['yes','no']:issue('latest_bluff_uncertain',seat=a['seat'])
 for p in parts[bvid]:
  for a in p['game']['assessments']:
   current=next(x for x in bg[bvid]['assessments'] if x['seat']==a['seat'])
   if a['decision']!=current['decision'] and not (bvid=='BV1U3p86dEJY' and a['seat']==10 and current['decision']=='no'):issue('bluff_part_latest_diff',seat=a['seat'],part=p['path'],old=a['decision'],current=current['decision'])
 field('bluff_assessments',None,bluffchecks,[{'path':p['path'],'sha256':sha(p['path'])} for p in parts[bvid]],level='prior_independent_video_audit_transcript_and_user_confirmation_not_new_media_review')
 field('endgame',None,end,[{'path':'data/extractions/S23/endgame_reviewed_sources.json','sha256':sha('data/extractions/S23/endgame_reviewed_sources.json')},{'path':entry['source_path'],'sha256':source_hash,**w}])
 field('supplemental_special_states',None,supp,[{'path':f+'/daily_audit.json','sha256':sha(f+'/daily_audit.json')}])
 record={'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'board':d['board'],'winner':d['winner'],'formal_ref':REF,'source':{'path':entry['source_path'],'sha256':source_hash,'cid':entry['cid'],'page':entry['page'],'origin':entry['transcript_origin'],'hash_matches':source_hash==entry['source_sha256']},'scope':['12座身份/姓名/个人阵营','胜方','逐轮投票/票权/结果','日夜死亡先后','显式技能/特殊状态','终局/拍刀','悍跳最终发布判断'],'counts':{'seats':len(d['seats']),'rounds':len(d['rounds']),'event_slots':len(ee),'known_event_slots':sum(e['action']!='unknown' for e in ee.values()),'unknown_event_slots':sum(e['action']=='unknown' for e in ee.values()),'ballots':len(v['ballots']),'votes':sum(len(b['votes']) for b in v['ballots']),'daily_patches':len(daily.get('event_patches',[])),'proof_objects':len(proof),'proofs_source_window_exact':sum(p['quote_matches_window'] is True for p in proof),'proofs_source_full_exact':sum(p['quote_matches_full_text'] is True for p in proof),'bluff_yes':sum(a['decision']=='yes' for a in bluffchecks)},'checks':checks,'survival_vote_checks':survival,'field_checks':fields,'proof_checks':proof,'recap':{'window':w,'rows':recap},'unpublished_terminal_checks':context['unpublished_terminal_checks'],'prior_audit_checks':daily.get('checks',[]),'issues':issues,'conclusion':'source_crosscheck_performed_not_all_fields_raw_media_verified','limitations':['本轮读取归档字幕/ASR与旁证；未批量回看原视频或回听音频。','文字引文一致不等于字幕逐字准确；未用原音消歧的口误保留。','unknown事件槽含模板占位，不将unknown个数当作必须用户核对数。','旧pending/早期判断按最新反馈及正式候选覆盖，不重新打开用户定案。']}
 records.append(record)
 recapdocs.append(f'## {len(records):02d} {d["date"]} g{d["game_number"]} {bvid} {d["board"]} winner={d["winner"]}\n角色 '+','.join(str(s['seat'])+s['role']+('狼混' if s['role']=='混血儿' and s['faction']=='werewolf' else '') for s in d['seats'])+'\n原复盘 '+''.join(x['text'] for x in recap)+'\n事件 '+json.dumps([{'n':r['number'],'night':{e['slot']:compact(e) for e in r['night'] if e['action']!='unknown'},'day':{e['slot']:compact(e) for e in r['day'] if e['action']!='unknown'}} for r in d['rounds']],ensure_ascii=False)+'\n')
(BASE/'per_game_audit.json').write_text(json.dumps({'ref':REF,'method':'read_only_published_field_source_audit','games':records},ensure_ascii=False,indent=2))
(BASE/'candidate_anomalies.json').write_text(json.dumps(anomalies,ensure_ascii=False,indent=2))
for i in range(0,75,15):(BASE/f'recap_batch_{i//15+1}.txt').write_text('\n'.join(recapdocs[i:i+15]))
print('GAMES',len(records),'COUNTS',dict(sum((collections.Counter(x['counts']) for x in records),collections.Counter())),'ANOMALIES',len(anomalies),collections.Counter(x['code'] for x in anomalies))
for x in anomalies:print(json.dumps(x,ensure_ascii=False)[:1000])
