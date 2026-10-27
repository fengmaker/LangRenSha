import subprocess,pathlib,hashlib,json,concurrent.futures
repo=pathlib.Path('/workspace/scratch/a7edd912716e/langrensha-cloud'); out=repo.parent/'audit-published/S23/evidence'; ref='origin/ci/full-acceptance'
rows=subprocess.check_output(['git','-c','core.quotePath=false','ls-tree','-r',ref,'data/extractions/S23','data/reports','data/games/S23','website/assets/bluffs/S23.json'],cwd=repo,text=True).splitlines()
selected=[]
for r in rows:
 meta,p=r.split('\t');oid=meta.split()[2]
 if p.endswith(('.png','.jpg','.jpeg','.py','.html')): continue
 if p.startswith('data/extractions/S23/game_reviews/') or p.startswith('data/extractions/S23/bluff_review/') or p.startswith('data/reports/S23_') or p.startswith('data/games/S23/') or p=='website/assets/bluffs/S23.json' or p=='data/extractions/S23/endgame_reviewed_sources.json':selected.append((p,oid))
def one(v):
 p,oid=v;dest=out/p;dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.exists():b=dest.read_bytes()
 elif (repo/p).exists() and subprocess.check_output(['git','hash-object',str(repo/p)],cwd=repo,text=True).strip()==oid:b=(repo/p).read_bytes();dest.write_bytes(b)
 else:b=subprocess.check_output(['git','show',ref+':'+p],cwd=repo);dest.write_bytes(b)
 return {'path':p,'git_blob':oid,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
manifest=[]
# Explicit individual text blobs only; no media files or tree-size requests.
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
 for i,v in enumerate(ex.map(one,selected),1):
  manifest.append(v)
  if i%100==0:print(i,len(selected),flush=True)
(out.parent/'evidence_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('DONE',len(manifest),sum(x['bytes'] for x in manifest),flush=True)
