import json,subprocess,hashlib,re,collections
from pathlib import Path
R=Path('/workspace/scratch/a7edd912716e/langrensha-cloud');O=Path('/workspace/scratch/a7edd912716e/audit-published/S22');REF='origin/ci/full-acceptance';P=json.loads((O/'recaps_b_input.json').read_text())
def blob(path):
 raw=subprocess.check_output(['git','show',REF+':'+path],cwd=R);return raw,hashlib.sha256(raw).hexdigest()
def jblob(path):
 raw,h=blob(path);return json.loads(raw),h
cache={};sources={}
for i in P:
 base=i['path'].rsplit('/',1)[0];d,dh=jblob(i['path']);rr,rh=jblob(base+'/复核记录.json');ex,eh=jblob('data/extractions/S22/voting/'+i['game_id'].split('-')[1]+'.json')
 sp=rr['source_path'];raw,sh=blob(sp);s=json.loads(raw);rows=s.get('body',s.get('segments',[])); seg=[]
 for row in rows:
  a=row.get('start_ms',row.get('start',row.get('from',0)));b=row.get('end_ms',row.get('end',row.get('to',0)))
  if 'from' in row or 'start' in row:a=round(a*1000);b=round(b*1000)
  seg.append({'start_ms':a,'end_ms':b,'text':row.get('text',row.get('content',''))})
 sources[i['game_id']]={'path':sp,'sha256':sh,'segments':seg};cache[i['game_id']]={'d':d,'rr':rr,'rr_sha':rh,'ex':ex,'ex_sha':eh}
F=collections.defaultdict(list)
def event(d,round,phase,slot):return [a for r in d['rounds'] if r['number']==round for a in r[phase] if a['slot']==slot]
def add(ix,field,query,new,a,b,reason,kind='conflict',confidence='high',coverage='not_found_in_checked_overrides'):
 i=P[ix-74];c=cache[i['game_id']];s=sources[i['game_id']]
 if query[0]=='event':old=event(c['d'],*query[1:])
 elif query[0]=='seat':old=next(x for x in c['d']['seats'] if x['seat']==query[1]).get(query[2])
 elif query[0]=='endgame':old=i['endgame']['phases']
 else:old=query[1]
 ev=[x for x in s['segments'] if x['end_ms']>=a and x['start_ms']<=b]
 prior=list(dict.fromkeys(v.get('conclusion','') for v in c['rr'].get('question_answers',{}).values()))
 F[ix].append({'finding_id':f"S22-B-{ix}-{len(F[ix])+1}",'field':field,'old_value':old,'candidate_value':new,'conclusion':reason,'type':kind,'confidence':confidence,'evidence_level':'same_source_text_crosscheck_not_audio','source':{'path':s['path'],'sha256':s['sha256'],'start_ms':a,'end_ms':b,'segments':ev},'existing_resolution_check':{'prior_ai_conclusions':prior,'note':'既有AI结论不是用户确认；保留已接受终局/延迟死亡/吞毒自爆结论。字段未落盘或关联字段冲突仍单列。','override_status':coverage},'official_mutation':False})
add(80,'R2.night.masquerade_verify.result',('event',2,'night','masquerade_verify'),{'result':'不在舞池'},2882260,2888070,'假面查询的是目标是否在舞池，原始字幕明确12号平民不在舞池；正式result=假面混入角色名。')
add(84,'R1.day.badge',('event',1,'day','badge'),{'action':'unknown','targets':[],'note':'删除首日重复移交；保留R2的6→11'},6291880,6308260,'6号首日当选、次夜中刀后才移交11；正式首日另记actor=null的移交11，和R2移交重复。既有AI回答也明确移交在第二夜死亡之后。')
add(84,'R3.night.wolf_attack / mechanical_action',('event',3,'night','mechanical_action'),{'wolf_attack':{'action':'attack','actor':9,'targets':[1]},'mechanical_action':{'action':'pass','targets':[]}},6312840,6319160,'复盘把小刀击杀1与破盾技能刀通过分开；正式把杀1填入机械技能槽且普通刀unknown，疑似普通刀/技能刀混淆。需结合本季槽位契约确认，不改变死者。','semantic_slot_candidate','medium')
add(85,'R2.night.seer_check',('event',2,'night','seer_check'),{'action':'check','actor':7,'targets':[11],'result':'狼人'},5269105,5278260,'连续复盘明确第二夜预言家验证11号狼人，正式该槽仍unknown。','sourced_omission')
add(86,'R2.night.masquerade_verify.result',('event',2,'night','masquerade_verify'),{'result':'不在舞池'},2189250,2194450,'原始转写明确假面验1号舞者不在舞池，正式result却为假面。')
add(86,'R3.night.masquerade_verify',('event',3,'night','masquerade_verify'),{'action':'verify','actor':4,'targets':[12],'result':'在舞池'},2205590,2215250,'复盘连续说12号平民在舞池并给12扣面具；正式查验槽unknown。','sourced_omission')
add(90,'R2.day.night_deaths',('event',2,'day','night_deaths'),{'action':'die','targets':[8]},4932340,4942890,'守5挡狼刀只说明狼刀未杀人，同夜女巫毒8；正式却记整夜peaceful[]，导致game_flow仍列8存活且terminal=null。已有AI结论也将8前夜已毒死作为后夜推导前提。')
add(101,'R1.night.seer_check.result',('event',1,'night','seer_check'),{'result':'猎人'},4991560,5004600,'盗宝大师7当夜选择猎人；复盘明确通灵师验7反馈猎人，不是物理底牌盗宝大师。')
add(101,'R1.night.dreamer_action',('event',1,'night','dreamer_action'),{'action':'dream','actor':1,'targets':[6]},5001430,5007800,'复盘明确首夜摄梦人梦游6号毒师，正式首夜梦游槽unknown。','sourced_omission')
add(112,'R2.night.wolf_attack',('event',2,'night','wolf_attack'),{'action':'attack','targets':[3]},3179470,3186890,'复盘明确追刀3号女巫；正式写刀9（通灵师），旁证第2日死亡补充又明确3号倒牌，原刀目标与同局后续存活矛盾。','conflict','high','night_death_3_already_overridden_in_voting_extraction_but_attack_target_not')
add(112,'endgame.phases[0].day',('endgame',),{'day':4,'note':'候选：第三天7号自爆之后入夜刀6，次白天放逐12后才拍刀'},3203780,3217340,'正式endgame.day=3且note说第三天放逐12；dossier将12放逐放第4天，连续复盘也为D3自爆→入夜刀6→白天放逐12→拍刀。存在终局挂错日的源内矛盾。','conflict','high','no_day_override_found')
add(116,'R3.night.witch_poison / R4.night.witch_poison',('event',3,'night','witch_poison'),{'R3':{'action':'pass','targets':[]},'R4':{'action':'poison','actor':6,'targets':[11]}},3380920,3396370,'复盘R3女巫通过，R4才毒最后机械狼11终局；正式毒11提早一夜。既有AI已判R3空过、终局也由causal_terminal限定R4夜，但毒药事实未跟随校正。','conflict','high','terminal_round4_night_already_overridden_but_poison_round_not')
add(120,'R1.night.seer_check.result',('event',1,'night','seer_check'),{'result':'好人'},4012350,4016010,'预言家反馈是好人；复盘中的平民为目标真实身份修饰语，正式result误记平民。')
add(126,'R2.day.night_deaths',('event',2,'day','night_deaths'),{'action':'die','targets':[5]},4907635,4923700,'守7挡刀形成狼刀平安，但女巫毒5仍应出局；正式整夜peaceful[]。终局复盘称11自爆后仅12末狼交牌，进一步排除5仍活；game_flow现仍列5且terminal=null。')
add(127,'R1.day.badge',('event',1,'day','badge'),{'action':'transfer','actor':4,'targets':[12]},6000590,6005750,'复盘明确4号被放逐后警徽交12女巫，正式徽处理仍unknown。','sourced_omission')
add(131,'R1.night.seer_check',('event',1,'night','seer_check'),{'action':'check','actor':8,'targets':[5],'result':'狼王'},5131795,5140635,'连续复盘明确首夜通灵师验5反馈狼王，正式该槽unknown。','sourced_omission')
add(131,'R2.night.treasure_choice',('event',2,'night','treasure_choice'),{'action':'choose','actor':7,'result':'平民'},5157865,5164580,'复盘明确盗宝7第二夜切为平民，正式选择槽unknown。','sourced_omission')
add(131,'R2.night.seer_check.result',('event',2,'night','seer_check'),{'result':'平民'},5157425,5164580,'正式已知通灵验7，但结果null；复盘明确反馈平民（盗宝已切平民）。','sourced_omission')
add(137,'R2.night.seer_check.result',('event',2,'night','seer_check'),{'result':'好人'},4232280,4236980,'预言家查6反馈好人；平民是复盘对目标的底牌说明，不是查验反馈。')
add(139,'R2.night.seer_check.result',('event',2,'night','seer_check'),{'result':'好人'},3731279,3737630,'预言家查4反馈好人，正式误记平民。')
add(139,'R3.night.seer_check.result',('event',3,'night','seer_check'),{'result':'好人'},3743249,3749209,'预言家查7反馈好人，正式误记猎人；不是通灵师精确底牌查验。')
add(140,'R2.night.masquerade_verify.result',('event',2,'night','masquerade_verify'),{'result':'不在舞池'},2416670,2423790,'复盘明确验6号舞者不在舞池；正式反馈误填目标底牌舞者。')
add(140,'R3.night.masquerade_verify.result',('event',3,'night','masquerade_verify'),{'result':'在舞池'},2439100,2449299,'复盘明确验5号白神在舞池；正式反馈误填底牌白痴。')
add(140,'R2.night.seer_check.result',('event',2,'night','seer_check'),{'result':'好人'},2430400,2433540,'预言家查4反馈好人，正式误填平民。')
add(141,'R2.day.night_deaths',('event',2,'day','night_deaths'),{'action':'die','targets':[12]},3090800,3101370,'第二夜狼刀12、守7、机械女巫空过，12唯一死因成立；正式死亡unknown且game_flow第2日仍unknown，既有AI已确认刀12但死亡未落盘。','causal_unique_candidate')
add(141,'R3.day.night_deaths',('event',3,'day','night_deaths'),{'action':'die','targets':[7]},3101370,3113270,'第三夜刀7，旁证原播报1973380–1991760ms已补7死亡；正式dossier仍unknown。此为已有旁证覆盖而未同步原字段，不重新询问用户。','raw_field_gap','high','night_death_7_already_overridden_in_voting_extraction')
add(141,'R4.night.wolf_attack',('event',4,'night','wolf_attack'),{'action':'attack','actor':6,'targets':[11]},3113270,3127149,'复盘明确机械狼普通刀11被守挡，再另用毒8；正式只存毒8，普通刀槽unknown。保留两动作而不把平安刀当整夜无死。','sourced_omission')
add(146,'R2.night.seer_check.result',('event',2,'night','seer_check'),{'result':'好人','note':'原目标4，号码交换后实际验到6号魔术师'},3186189,3191410,'完整原句明确查4实际验6魔术师为好人，正式查验目标4保留正确但结果null。','sourced_omission')
add(147,'R1.night.mechanical_action',('event',1,'night','mechanical_action'),{'action':'pass','actor':7,'targets':[],'note':'首夜未学习；第二夜才学1守卫'},4718940,4730810,'复盘明示首夜未学/未模仿并通过，既有AI亦已接受该学习时点；正式首夜动作仍unknown，不能把未知等同已确认空过。','sourced_omission')
# Mixed-blood raw fields: derived alignment may already be correct downstream; do not claim a website/statistics defect.
for ix,seat,fac,a,b in [(106,3,'good',3775115,3794105),(109,6,'good',3199730,3206440),(130,11,'good',4089110,4099490),(133,9,'good',6092680,6101410),(136,10,'werewolf',5068780,5075580),(139,9,'good',3709900,3722900),(142,9,'werewolf',4903090,4907960),(145,9,'werewolf',5272720,5277680)]:
 add(ix,f'seats[seat={seat}].faction',('seat',seat,'faction'),fac,a,b,'真实榜样与mixed_blood_alignment事件、复盘阵营已明确，但座位原始faction为null。父网站映射审计已确认发布层按唯一榜样正确派生，因此这是已派生覆盖的原字段保留，不是新问题，不建议改正式值，不重新请用户确认。','derived_covered_not_issue','high','parent_site_audit_verified_unique_model_faction_derivation_no_change_recommended')
for ix,r,a,b in [(106,2,3810445,3817215),(136,1,5078420,5082280)]:
 add(ix,f'R{r}.night.seer_check.result',('event',r,'night','seer_check'),{'result':'好人'},a,b,'预言家的好人反馈被目标的真实平民底牌替代；保留查验目标，反馈与底牌分开。')
# Explicitly record omissions where source phrasing is not sufficiently clean for unattended replacement.
add(86,'R3.night.masquerade_verify.target source wording',('event',3,'night','masquerade_verify'),{'target_candidate':12,'result_candidate':'在舞池'},2205590,2215250,'目标12与同夜舞池/面具因果一致，但原ASR漏掉“验证”部分，恢复动作仍需按上下文判断；不把机器稿修补伪称原音听清。','evidence_boundary','medium')
# Recover 106's recap from the actual long transcript, not stale absent-marker recap.txt.
for i in P:
 ix=74+P.index(i);c=cache[i['game_id']];s=sources[i['game_id']]
 if ix==106:a,b=3773715,3839885
 else:
  m=re.findall(r'\[([\d.]+)[–-]([\d.]+)\]',i['recap']);a=round(float(m[0][0])*1000);b=round(float(m[-1][1])*1000)
 compact={k:i[k] for k in ['game_id','date','board','winner','path','dossier_sha256','recap_path','recap_sha256','endgame_sha256']}
 compact.update({'sorted_index':ix,'scope_checked':['连续复盘的12座真实角色','混血/盗宝/机械/傀儡/面具等关键状态','复盘已知夜间行动及死亡','主要白天出局/警徽流转/终局','实际底牌与查验反馈分离'],'not_checked':['原音/原视频直接复听复看','逐人逐轮投票（父审计负责）','姓名牌/照片映射重做','所有unknown槽的穷尽补全'],'source_text':{'path':s['path'],'sha256':s['sha256'],'start_ms':a,'end_ms':b},'review_record':{'path':i['path'].rsplit('/',1)[0]+'/复核记录.json','sha256':c['rr_sha']},'voting_extraction':{'path':'data/extractions/S22/voting/'+i['game_id'].split('-')[1]+'.json','sha256':c['ex_sha'],'terminal':c['ex'].get('game_flow',{}).get('terminal')},'evidence_level':'continuous_recap_machine_text_crosscheck','original_media_direct_review':False,'roles_and_winner':'复盘与正式12座角色、整局胜方未发现新增明确冲突；这不是原媒体核实完成','findings':F[ix],'conclusion':('发现明确原字段候选差异或已有推导未同步项' if any(f['type'] not in ['derived_covered_not_issue','evidence_boundary'] for f in F[ix]) else '仅有已派生覆盖的原字段保留，不建议修正') if F[ix] else '连续复盘主要已知字段未见新增明确矛盾；不等同所有未知字段/原媒体已核实','gaps':['原音未复听；机器稿字词/完整性仍有边界','逐人票型及页面实际映射由父审计另行处理']})
 if ix==106:compact['gaps'].append('复盘原文.txt仍是未定位占位；本轮按既有复核记录3773.715–3839.885秒定位回读原始全文转写，未把占位当有效复盘。')
 if ix==112:compact['preserved_decisions']=['保留既有medium因果结论：首日2号自爆前12号已持徽；本轮不以复盘口误自动推翻。','第三夜查验对象按既有后句澄清保留8，不重开1/8。']
 if ix in [93,113,130,140,141,146]:compact['preserved_decisions']=['吞毒/中刀后竞选阶段自爆按既有接受口径保留，不重复计死、不以规则自动重开。']
 if ix==138:compact['preserved_decisions']=['8/18第3局第4天用户直接确认1/4/6/7/8/9投12、12投6，原用户定案不重开。']
 i['audit']=compact
result={'baseline':'3476a56af155f36a0d0050abc1660ed0d6fd538a','season':'S22','slice':'sorted dossier paths [74:148]','games':74,'continuous_recap_text_games':74,'recap_placeholder_recovered_games':1,'original_media_direct_review_games':0,'findings_count':sum(sum(f['type'] not in ['derived_covered_not_issue','evidence_boundary'] for f in fs) for fs in F.values()),'games_with_findings':len([fs for fs in F.values() if any(f['type'] not in ['derived_covered_not_issue','evidence_boundary'] for f in fs)]),'derived_covered_not_issues':8,'evidence_boundary_notes':1,'classification_note':'所有候选均只读输出；原字幕/ASR回读不是原音或独立二源。raw_field_gap可能已有网站派生覆盖；不把它当统计错误。无问题项仅表示已知主要字段在复盘文本范围内未见矛盾。','items':[i['audit'] for i in P]}
(O/'recaps_b.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
summary=['# S22 后74局复盘字段审计','',f"基线 `{result['baseline']}`；74局均按连续复盘文本对照，原音/视频直接复核0局。",f"差异/缺口候选 {result['findings_count']} 项，涉及 {result['games_with_findings']} 局；其中含原字段已可派生的阵营空值，不等于网站统计错误。",'','|局|字段|旧→候选|结论|','|---|---|---|---|']
for i in P:
 for f in i['audit']['findings']:
  summary.append('|'+i['game_id']+'|'+f['field']+'|'+json.dumps(f['candidate_value'],ensure_ascii=False).replace('|','/')+'|'+f['conclusion'].replace('|','/')+'|')
(O/'recaps_b_summary.md').write_text('\n'.join(summary)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='items'},ensure_ascii=False,indent=2))
print('output',O/'recaps_b.json')
