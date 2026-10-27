import subprocess,json,re,hashlib,collections
from pathlib import Path
O=Path('/workspace/scratch/a7edd912716e/audit-published/S22');R=Path('/workspace/scratch/a7edd912716e/langrensha-cloud');REF='3476a56af155f36a0d0050abc1660ed0d6fd538a'
B=json.loads((O/'review_bundle.json').read_text());reg=json.loads((O/'evidence_registry.json').read_text());defaults=json.loads((O/'default_abstention_review_candidates.json').read_text());windows=[];cache={};find=[];dispositions=[]
def source(p):
 if p not in cache:
  raw=subprocess.check_output(['git','show',REF+':'+p],cwd=R);x=json.loads(raw);ss=x.get('segments') or [{'start_ms':int(round(a['from']*1000)),'end_ms':int(round(a['to']*1000)),'text':a['content']} for a in x.get('body',[])]
  cache[p]=(raw,ss)
 return cache[p]
def evs(bv,bid,extra=0):
 x=B[bv];p=x['extraction']['source_path'];raw,ss=source(p);ev=x['extraction']['evidence'].get(bid,[]);out=[]
 for e in ev:
  if e.get('path')!=p or e.get('start_ms') is None:continue
  st=e['start_ms'];en=e['end_ms']+extra;z=[a for a in ss if a['end_ms']>=st and a['start_ms']<=en]
  w={'source_path':p,'source_sha256':hashlib.sha256(raw).hexdigest(),'original_media_start_ms':st,'original_media_end_ms':en,'segments':z,'evidence_type':'archived_platform_caption_or_ASR_text_read_this_audit_not_audio_video','source_hash_matches_extraction':hashlib.sha256(raw).hexdigest()==x['extraction'].get('source_sha256')};windows.append({'bvid':bv,'ballot_id':bid,**w});out.append(w)
 return out
def record(bv,bid,code,old,new,note,conf='high_textual_evidence',extra=0):
 x=B[bv];v=next(b for b in x['voting']['ballots'] if b['id']==bid)
 a={'id':'S22-V-'+str(len(find)+1).zfill(3),'bvid':bv,'game_id':x['dossier']['slug'],'date':x['dossier']['date'],'day':v['day'],'ballot_id':bid,'field_scope':code,'old_value':old,'candidate_value':new,'conclusion':'candidate_correction_supported_by_archived_text','confidence':conf,'evidence':evs(bv,bid,extra),'reason':note,'primary_audio_video_review':False,'formal_data_changed':False,'dependencies':['逐人票型显示','投票参与/弃票统计','本轮结果显示（如变更winner）','票权与日序重放'],'existing_decision_policy':'尊重用户默认弃票规则；此处检查规则前提是否满足，不撤销用户规则。'};find.append(a);return a['id']
groups={7:3,16:6,24:4,27:10,28:1,30:9}
split={1:4,11:2,12:4,13:2,18:1,22:3,25:1,29:4,31:5,33:2,34:1,36:4,37:7,42:2,43:1}
malformed={4:(5,10),5:(3,1),35:(2,12),41:(12,10)}
for i,x in enumerate(defaults):
 bv=x['bvid'];bid=x['ballot'];ids=[];status='preserve_existing_default';note='未发现足以覆盖现有默认弃票口径的新明确唱票；不重开用户定案。'
 if i in groups:
  tar=groups[i];new=[{'voter':v,'target':tar,'state':'cast'} for v in x['default_voters']];old=[{'voter':v,'target':None,'state':'abstained'} for v in x['default_voters']]
  ids=[record(bv,bid,'votes',old,new,'真实唱票“其余（所有）玩家投给”是对其余合法投票人的集合明确投向，不能视为未播报。按当轮存活/票权展开即可；不改变现场放逐结果。')];status='high_confidence_correction';note='集合播报被错误落成默认弃票。'
 elif i in split:
  tar=split[i];ids=[record(bv,bid,'votes[12]',{'voter':12,'target':None,'state':'abstained'},{'voter':12,'target':tar,'state':'cast'},'原字幕相邻条目的“十”与“2号”连读为12号，后一条接明确投向；完整顺序里2号已在前面唱过。分行不是新投票人，也不是弃票。')];status='high_confidence_text_normalization';note='12号数字在相邻字幕片段断开，明确票向遗漏。'
 elif i in malformed:
  voter,tar=malformed[i];ids=[record(bv,bid,f'votes[{voter}]',{'voter':voter,'target':None,'state':'abstained'},{'voter':voter,'target':tar,'state':'cast'},'完整唱票仍可辨认该座位和目标；机械重复/无标点黏连使旧提取漏票。连续上下文及结果支持目标，候选不是凭总数分配票。')];status='high_confidence_text_normalization';note='票向被重复数字或句界解析遗漏。'
 elif i in [9,10]:
  ids=[record(bv,bid,'eligible_voters_and_votes[6]',{'eligible':True,'vote':{'voter':6,'target':None,'state':'abstained'}},{'eligible':False,'vote':None},'第2日开局3588700–3590940ms已明确“昨夜6号玩家倒牌”，3591600–3601500ms移徽3号，复盘7545–7549s亦明示毒6出局。第3/4日不能把已死6当有票权后默认弃票。相关死亡错误另见recaps_a。')];status='high_confidence_ineligible_voter';note='已死亡6号被错误保留在后续票权。'
 elif i==21:
  ids=[record(bv,bid,'duplicate_ballot',B[bv]['voting']['ballots'],{'remove_ballot_id':'ballot-4','retain_ballot_ids':['causal-ballot-review-day-4-exile-initial-d4','causal-ballot-review-day-4-exile-revote-d4'],'renumber_final_revote':2},'既有2026-10-25因果定案明确D4仅首轮＋王子技能复投两轮；正确因果复投已补入，但同一7009060–7027540ms唱票对应旧全弃票ballot-4仍保留，产生不存在的中间第三轮。应落实已接受定案，不要求用户重新裁定。')];status='accepted_fix_not_fully_applied';note='旧错误票轮与已补正确同轮并存。'
 elif i==26:
  ids=[record(bv,bid,'votes[7,8]',[{'voter':s,'target':None,'state':'abstained'} for s in [7,8]],[{'voter':s,'target':9,'state':'cast'} for s in [7,8]],'ASR唱票“七号特别九号、八号特别九号”处于逐席投给序列；其余10席已齐，最终明确9号10.5票（10张＋警徽半票），缺的7/8只能均投9，且原句指向9，因果唯一。真实出局7由诡术换位，不能改为票最多9出局。','high_contextual_deduction')];status='high_confidence_contextual_deduction';note='ASR同音词与票数/顺序共同唯一约束两张票。'
 elif i in [3,6,14,17,38,40]:
  status='ambiguous_transcription_no_correction';note='存在数字或播报缺损，但本轮不凭排序/音近猜填；现默认弃票规则保留，原媒体仍未核。'
  evs(bv,bid)
 dispositions.append({'index':i,**x,'review_conclusion':status,'note':note,'finding_ids':ids})
# true final correction omitted by old evidence boundary
bv='BV1iDGK61E1c';bid='ballot-3';f=record(bv,bid,'winner',2,10,'5756820ms初次误宣2号3.5票出局，5763930ms明确叫停，5776349–5778149ms纠正10号4票出局；随后10号遗言并离场。现有旁证截于5770489ms，漏掉最终更正。dossier.exile_result本来已为10，voting.winner仍2；发布层不会互相覆盖。',extra=60000)
# Explicit in-place correction in roll call
record('BV1GmTc61EMA','ballot-2','votes[11]',{'voter':11,'target':7,'state':'cast'},{'voter':11,'target':5,'state':'cast'},'逐席唱票先说11→7，紧接改口“十二十一号投给5号，12号投给5号”；结果6.5比6、5号出局与11→5相符，而旧记录仍保留早先11→7。保持最终出局5不变。','high_contextual_deduction')
# default-only raw report says unweighted winner differs due exchange: preserve
excluded=[{'bvid':'BV1hZMp63Esx','ballot_id':'ballot-3','status':'not_an_error','reason':'10号得票最高但诡术交换使3号实际被放逐；连续复盘明确原投票目标/实际出局不同。'}, {'bvid':'BV1BPNB6QE1V','ballot_id':'ballot-2','status':'not_an_error_for_result','reason':'9号最高票、7号实际出局由诡术换位；结果不改。7/8票缺口另列。'}, {'bvid':'BV1JNgj6gEaf','ballot_id':'ballot-2','status':'not_an_error','reason':'4号最高票、6号实际出局由交换；不能凭票数改现场结果。'}, {'bvid':'BV19Ggx6xEqE','ballot_id':'ballot-2','status':'already_resolved_keep_current','reason':'旧ASR4/7票与当前不同，已有独立音频转写和因果修订明确4→7、7→1；不重开旧疑点。'}, {'scope':'8 mixed-blood seat faction null','status':'derived_layer_covers_no_correction','reason':'网站发布层由唯一榜样推导阵营，源null保留不应单独当事实错误。'}]
(O/'voting_findings.json').write_text(json.dumps({'baseline':REF,'findings':find,'excluded_candidates':excluded,'summary':{'findings':len(find),'affected_games':len(set(f['bvid'] for f in find)),'default_abstention_rounds_reviewed':len(dispositions),'default_abstention_votes_reviewed':sum(len(x['default_voters']) for x in defaults),'group_vote_rounds':len(groups),'group_vote_corrections':sum(len(defaults[i]['default_voters']) for i in groups),'split_12_rounds':len(split)}},ensure_ascii=False,indent=2))
(O/'default_abstention_reviewed.json').write_text(json.dumps(dispositions,ensure_ascii=False,indent=2))
(O/'voting_primary_text_windows.json').write_text(json.dumps(windows,ensure_ascii=False,indent=2))
print('findings',len(find),'games',len(set(f['bvid'] for f in find)))
print('default statuses',collections.Counter(x['review_conclusion'] for x in dispositions))
