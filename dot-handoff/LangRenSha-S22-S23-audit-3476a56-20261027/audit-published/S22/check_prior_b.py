import json,subprocess,hashlib
from pathlib import Path
R=Path('/workspace/scratch/a7edd912716e/langrensha-cloud');O=Path('/workspace/scratch/a7edd912716e/audit-published/S22');report=json.loads((O/'recaps_b.json').read_text());bvs={i['game_id'].split('-')[1] for i in report['items'] if i['findings']}
ps=['data/reports/S22_技能结算补充复核.json','data/reports/S22_日序与阵营更正.json','data/reports/S22_正式规则对齐记录.json','data/reports/S22_疑点推理复核.json','data/extractions/S22/causal_review_20261025/accepted.json','data/extractions/S22/causal_review_20261025/dossier_patch_plan.json','data/extractions/S22/causal_review_20261025/primary_overrides.json','data/extractions/S22/疑点推理复核/primary_approved.json','data/extractions/S22/疑点推理复核/mechanical_plan.json','data/extractions/S22/疑点推理复核/special_plan.json']
output=[]
for p in ps:
 raw=subprocess.check_output(['git','show','origin/ci/full-acceptance:'+p],cwd=R);x=json.loads(raw); hits=[]
 def walk(x,key=''):
  if isinstance(x,dict):
   bv=x.get('bvid')
   if bv in bvs:hits.append(x);return
   for k,v in x.items():
    if k in bvs:hits.append({'bvid':k,'record':v})
    else:walk(v,k)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(x);output.append({'path':p,'sha256':hashlib.sha256(raw).hexdigest(),'matched_game_records':hits})
 print(p,len(hits),'matched')
 for h in hits:
  if p.endswith('dossier_patch_plan.json') or p.endswith('primary_overrides.json') or p.endswith('S22_正式规则对齐记录.json') or p.endswith('S22_技能结算补充复核.json'):print(str(h)[:1100])
(O/'prior_resolution_b.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
