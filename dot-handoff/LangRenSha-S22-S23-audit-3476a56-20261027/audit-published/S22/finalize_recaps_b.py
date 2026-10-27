import json,hashlib,collections
from pathlib import Path
O=Path('/workspace/scratch/a7edd912716e/audit-published/S22');p=O/'recaps_b.json';x=json.loads(p.read_text());pr=json.loads((O/'prior_resolution_b.json').read_text())
for i in x['items']:
 bv=i['game_id'].split('-')[1];refs=[]
 for r in pr:
  matches=[h for h in r['matched_game_records'] if h.get('bvid')==bv]
  if matches:refs.append({'path':r['path'],'sha256':r['sha256'],'matched_records':len(matches)})
 i['prior_specialized_reports_checked']=refs
 for f in i['findings']:
  if i['sorted_index']==141 and f['field']=='R3.day.night_deaths':
   f['type']='derived_covered_not_issue';f['conclusion']+='已作为已有派生覆盖记录，不算新增事实问题，不建议为此次审计重开确认。'
  if f['type']=='derived_covered_not_issue':f['count_as_new_issue']=False;f['recommendation']='保留既有定案和派生结果；不建议正式修正'
  elif f['type']=='evidence_boundary':f['count_as_new_issue']=False
  else:f['count_as_new_issue']=True
  f['existing_resolution_check']['specialized_reports_checked']=refs
 issues=[f for f in i['findings'] if f['count_as_new_issue']]
 i['new_issue_candidates']=len(issues)
 if not issues:
  i['conclusion']='已知主要字段在连续复盘文本范围内未见新增明确冲突；已有派生覆盖保留，不建议重开' if i['findings'] else i['conclusion']
fs=[f for i in x['items'] for f in i['findings']];issues=[f for f in fs if f['count_as_new_issue']]
x['findings_count']=len(issues);x['games_with_findings']=sum(i['new_issue_candidates']>0 for i in x['items']);x['derived_covered_not_issues']=sum(f['type']=='derived_covered_not_issue' for f in fs);x['candidate_breakdown']=dict(collections.Counter(f['type'] for f in issues));x['specialized_report_manifest']={'path':str(O/'prior_resolution_b.json'),'sha256':hashlib.sha256((O/'prior_resolution_b.json').read_bytes()).hexdigest(),'repository_reports_checked':len(pr)}
x['classification_note']='30个新增候选字段，不是30个已证实网站错误；其余9项已有派生覆盖（8局混血阵营、1局夜死）及1条证据边界不计新问题。已比对逐局复核记录、voting extraction及10份专项accepted/patch/report。原字幕/ASR回读仍非原音直接核实。'
p.write_text(json.dumps(x,ensure_ascii=False,indent=2))
lines=['# S22 后74局复盘字段审计','',f"固定基线 `{x['baseline']}`；74局连续复盘机器文本对照，原音/原视频直接核验0局。",f"新增候选字段 {x['findings_count']} 项，涉及 {x['games_with_findings']} 局；9项已派生覆盖不计新问题（8局混血阵营、1局夜死）。",'','## 最高优先级','', '- BV1Abgy6tEP8：第2夜女巫毒8，但夜死字段peaceful[]，game_flow仍列8存活，terminal=null。','- BV12Mur6nEns：第2夜女巫毒5，但夜死peaceful[]，game_flow仍列5存活，terminal=null。','- BV1DFM26ME2o：女巫毒11错写第3夜；原始复盘和已接受终局都指向第4夜。','- BV1xm3J6wEbr：通灵师查盗宝7应反馈猎人，正式result为盗宝大师。','- BV1jYKV6SEwK/BV1fPKY6gEFp/BV1tj8p6RE2h：假面查询的在/不在舞池反馈混入角色名。','- BV1oXMB6fEQ4：第2夜原刀写9而复盘与死亡播报均指3；终局day3与第4天放逐12冲突。','', '以上都是只读候选，不直接改动已有事实。5个重点已回读原始字幕/ASR时间窗并固化SHA，见top_b_primary_text_windows.json；不能称为原音直接复核。','', '## 逐局覆盖与新增候选','', '|局ID|新增候选数|结论|','|---|---:|---|']
for i in x['items']:lines.append(f"|{i['game_id']}|{i['new_issue_candidates']}|{i['conclusion']}|")
lines+=['','## 具体字段','', '|局ID|字段|候选|结论|','|---|---|---|---|']
for i in x['items']:
 for f in i['findings']:
  if f['count_as_new_issue']:lines.append('|'+i['game_id']+'|'+f['field']+'|'+json.dumps(f['candidate_value'],ensure_ascii=False).replace('|','/')+'|'+f['conclusion'].replace('|','/')+'|')
(O/'recaps_b_summary.md').write_text('\n'.join(lines)+'\n')
# Audit integrity, not factual acceptance.
assert len(x['items'])==74 and len({i['game_id'] for i in x['items']})==74
assert all(len(i['dossier_sha256'])==64 and len(i['source_text']['sha256'])==64 for i in x['items'])
assert all(f['source']['segments'] for f in fs)
assert x['findings_count']==30
print({'new_candidates':len(issues),'games':x['games_with_findings'],'covered_nonissues':x['derived_covered_not_issues'],'candidate_breakdown':x['candidate_breakdown'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
