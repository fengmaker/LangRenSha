import pathlib,json,hashlib,re,collections
B=pathlib.Path(__file__).resolve().parent;E=B/'evidence'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def check(name,value,detail=None):
 checks.append({'check':name,'passed':bool(value),'detail':detail});assert value,(name,detail)
M=read(B/'complete_evidence_manifest.json')
for x in M:
 p=E/x['path'];b=p.read_bytes();check('evidence_sha256:'+x['path'],sha(p)==x['sha256']);check('git_blob:'+x['path'],hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==x['git_blob'])
G=read(B/'per_game_audit.json')['games'];C=read(B/'manual_semantic_coverage_75.json');F=read(B/'semantic_findings.json')['findings'];GG={g['bvid']:g for g in G}
check('exact75records',len(G)==75 and len({g['bvid'] for g in G})==75 and {g['bvid'] for g in G}=={c['bvid'] for c in C})
check('manual_scope_not_exaggerated',all(c['manual_semantic_reading']['status']=='completed_final_recap_only' for c in C))
check('source_binding_all75',len(read(B/'source_manifest.json'))==75 and all(x.get('hash_matches') for x in read(B/'source_manifest.json')))
check('unique_candidate_ids',len(F)==len({x['id'] for x in F}))
check('all_candidates_unapplied',all(x['status']=='candidate_only_not_applied' and not c['applied'] for x in F for c in x['changes']))
field_count=0
for x in F:
 for c in x['changes']:
  p=E/c['formal_path'];d=read(p);check('formal_candidate_anchor_hash:'+x['id']+c['field'],sha(p)==c['formal_sha256']);f=c['field'];expected=None
  m=re.fullmatch(r'rounds\[(\d+)\]\.(night|day)\.([^\.]+)(?:\.(.+))?',f)
  if m:
   n,ph,slot,sub=m.groups();expected=next(e for r in d['rounds'] if r['number']==int(n) for e in r[ph] if e['slot']==slot);expected=expected.get(sub) if sub else expected
  elif f=='seats[4].faction':expected=next(s['faction'] for s in d['seats'] if s['seat']==4)
  elif f=='voting.ballot-2.eligible_voters/votes':expected=d['ballots'][1]
  else:raise ValueError(f)
  check('candidate_oldvalue_matches_actual:'+x['id']+f,expected==c['formal_current_value']);field_count+=1
 for a in x['source_evidence']:
  check('source_quote_hash:'+x['id'],sha(E/a['path'])==a['sha256']);check('quote_rows_nonempty:'+x['id'],len(a['rows'])>0 and a['quote']=='\n'.join(r['text'] for r in a['rows']))
check('candidate42fields',field_count==42,field_count)
check('metadata59preserved_58_were_initial_unexplained',sum(c['kind']=='daily_patch_metadata_preserved_in_formal_context' for g in G for c in g['checks'])==59)
check('machine0unexplaineddiff',read(B/'candidate_anomalies.json')==[])
check('three_exact_original_frames',sum(x['kind']=='saved_original_frame_directly_viewed' for x in M)==3)
summary={'passed':all(x['passed'] for x in checks),'check_count':len(checks),'evidence_files':len(M),'evidence_total_bytes':sum(x['bytes'] for x in M),'candidate_records':len(F),'candidate_fields':field_count,'candidate_games':len({x['bvid'] for x in F}),'formal_data_mutations_performed':False,'remote_publish_performed':False,'checks':checks}
(B/'validation_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=False,indent=2))
