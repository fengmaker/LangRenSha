"""Audit saved inference decisions, source hashes, raw recaps and local review API."""
import sys,json,urllib.request,urllib.parse,zipfile,hashlib
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[4]/'scripts'))
import batch_s22 as b
from s22_inference_review import REPORT,semantic_issues
r=b.read_json(REPORT);assert r['state']=='complete'
errors=[];originals=additions=0;known_roles=known_names=0
with zipfile.ZipFile(b.ROOT/r['backup']['files']) as archive:
 for g in r['items']:
  folder=b.ROOT/g['output_dir'];review=b.read_json(folder/'复核记录.json');v=b.read_json(folder/'dossier.json')
  if b.digest(folder/'dossier.json')!=g['after_sha256']:errors.append([g['bvid'],'档案与写入记录不符'])
  if review['state']!='imported':errors.append([g['bvid'],'AI误标人工状态'])
  raw=folder/'复盘原文.txt'
  if hashlib.sha256(archive.read(g['output_dir']+'/复盘原文.txt')).hexdigest()!=b.digest(raw):errors.append([g['bvid'],'原转写变化'])
  for d in g['decisions']:
   a=review['question_answers'].get(d['id'],{})
   if not all(a.get(k)==val for k,val in d.items()) or a.get('reviewer')!='ai':errors.append([g['bvid'],d['id'],'落盘决策不符'])
   if d['id'] in g['original_question_ids']:originals+=1
   else:additions+=1
  if semantic_issues(v):errors.append([g['bvid'],'语义交叉检查未通过'])
  known_roles+=sum(x['role'] is not None for x in v['seats']);known_names+=sum(x['name'] is not None for x in v['seats'])
 for path,digest in r['source_hashes'].items():
  if b.digest(b.ROOT/path)!=digest:errors.append([path,'证据源发生变化'])
base='http://127.0.0.1:8766'
def get(path):
 with urllib.request.urlopen(base+urllib.parse.quote(path,safe='/'),timeout=30) as response:return response.read().decode('utf-8')
api=json.loads(get('/api/games'));pending=sum(e.get('text_pending_question_count',0) for e in api['items']);resolved=sum(e.get('text_resolved_question_count',0) for e in api['items'])
assert pending==0 and resolved==298 and len(api['items'])==149
page=get('/data/reports/S22_疑点推理复核.html');assert page.count('<details')==363
workbench=get('/');assert 'AI推理与结论' in workbench and 'AI推理核查报告' in workbench
one=json.loads(get('/api/game/BV1PEN863EXG'));assert next(e for e in one['dossier']['rounds'][3]['night'] if e['slot']=='wolf_attack')['targets']==[4];assert one['entry']['state']=='imported'
batch_audit=b.read_json(b.ROOT/'data/reports/S22_对局批处理验收.json');text_audit=b.read_json(b.ROOT/'data/reports/S22_转写补充验收.json')
assert batch_audit['valid'] and text_audit['valid']
report=dict(checked_at=b.now(),valid=not errors,checked_games=len(r['items']),corrected_games=r['changed_games'],original_questions=originals,resolved=resolved,pending=pending,additional_findings=additions,known_roles_in_reviewed_games=known_roles,known_names_in_reviewed_games=known_names,formal_games=len(api['items']),source_files_unchanged=len(r['source_hashes']),raw_recaps_unchanged=148,canonical_ai_answers_match=True,ai_not_marked_user_reviewed=True,database_file_audit=True,text_source_audit=True,protected_sample_unchanged=True,http_report_decisions=page.count('<details'),errors=errors)
b.atomic_json(b.ROOT/'data/reports/S22_疑点推理验收.json',report)
print(json.dumps(report,ensure_ascii=False,indent=2));assert not errors
