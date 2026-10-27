import pathlib,json,subprocess,hashlib
repo=pathlib.Path('/workspace/scratch/a7edd912716e/langrensha-cloud');out=repo.parent/'audit-published/S23/evidence'
entries=[json.loads(p.read_text()) for p in out.glob('data/extractions/S23/game_reviews/*/entry.json')]
rows=subprocess.check_output(['git','-c','core.quotePath=false','ls-tree','-r','origin/ci/full-acceptance','data/seasons/S23'],cwd=repo,text=True).splitlines();tree={p:m.split()[2] for m,p in [r.split('\t') for r in rows]}
wanted={e['source_path']:e['source_sha256'] for e in entries}
print('entries',len(entries),'source paths',len(wanted),flush=True)
if len(entries)!=75:raise SystemExit('not yet ready')
ids=[tree[p] for p in wanted if p in tree]
p=subprocess.run(['git','-c','fetch.negotiationAlgorithm=noop','fetch','--no-tags','--no-write-fetch-head','--recurse-submodules=no','origin',*ids],cwd=repo,capture_output=True,text=True)
print('fetch text source status',p.returncode,flush=True)
if p.returncode:print(p.stderr);raise SystemExit(p.returncode)
manifest=[]
for p,expected in wanted.items():
 if p not in tree:manifest.append({'path':p,'status':'not in tree'});continue
 b=subprocess.check_output(['git','show','origin/ci/full-acceptance:'+p],cwd=repo);dest=out/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b);sha=hashlib.sha256(b).hexdigest()
 manifest.append({'path':p,'git_blob':tree[p],'sha256':sha,'expected_sha256':expected,'hash_matches':sha==expected,'bytes':len(b)})
(out.parent/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
print('DONE sources',len(manifest),'hash matches',sum(x.get('hash_matches',False) for x in manifest),flush=True)
