"""Record the completed, scoped import and website publication receipts."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from incremental_common import read_json, write_json, load_state, save_state

BASE = ROOT/'data/reports/S23/incremental'
BV = ['BV1Gnxm6sEjQ','BV1Qnxm6sEQq','BV1anxm6sEWy']
state=load_state(ROOT,'S23')
items=[next(i for i in state['items'].values() if i['entry']['bvid']==bv) for bv in BV]
assert all(all(i['phases'].get(p)=='done' for p in ['database','formal','bluffs','publish','verify']) for i in items)

last=read_json(ROOT/'website/artifacts/publication-acceptance-partial.json')
assert last['source']['selected_bvids']==BV[2:]
last_path=BASE/f'publication_acceptance_{BV[2]}_20261104.json'
last_path.write_bytes((ROOT/'website/artifacts/publication-acceptance-partial.json').read_bytes())
acceptances=[read_json(BASE/f'publication_acceptance_{bv}_20261104.json') for bv in BV]
assert all(r['state']=='passed' and r['api']['source_games_matched']==1 for r in acceptances)
assert all(r['source']['selected_bvids']==[bv] for r,bv in zip(acceptances,BV))
release=acceptances[0]['api']['release_id']
assert all(r['api']['release_id']==release for r in acceptances)
retained=read_json(BASE/'retained_release_check_20261104.json')
site=read_json(BASE/'new_games_site_check_20261104.json')
assert retained['state']==site['state']=='passed'
backup=ROOT/'data/backups/workflow-20261103T162949/receipt.json'
assert read_json(backup)['archive_catalog_valid'] is True
review=ROOT/'data/manual_review/feedback/S23_逐局复核意见_20261104_20261103.json'

# The workflow writes sidecars with LF while the importer initially wrote CRLF.
# Their JSON values must still equal the accepted derivations. Keep the actual
# published source bytes and refresh only this batch's recorded file hashes.
for item in items:
    formal=ROOT/item['formal_dir']
    accepted=read_json(ROOT/item['accepted_formal_path'])
    assert read_json(formal/'rule_derivations.json')==accepted['derivations']
    for filename,prior in item['formal_files'].items():
        actual=hashlib.sha256((formal/filename).read_bytes()).hexdigest()
        if filename!='rule_derivations.json':
            assert actual==prior,(item['entry']['bvid'],filename)
        item['formal_files'][filename]=actual
    item.update(published_release_id=release,
                publication_acceptance_path=f'data/reports/S23/incremental/publication_acceptance_{item["entry"]["bvid"]}_20261104.json',
                application_receipt='data/reports/S23/incremental/application_20261104.json')
save_state(ROOT,'S23',state)

summary={'state':'passed','mode':'partial','release_id':release,'accepted_games':3,
         'detail_requests':sum(r['requests']['detail_requests'] for r in acceptances),
         'browser_pages':sum(r['browser']['page_count'] for r in acceptances),
         'individual_reports':[f'data/reports/S23/incremental/publication_acceptance_{bv}_20261104.json' for bv in BV],
         'special_site_report':'data/reports/S23/incremental/new_games_site_check_20261104.json',
         'retained_report':'data/reports/S23/incremental/retained_release_check_20261104.json'}
write_json(BASE/'publication_acceptance_20261104.json',summary)
receipt={'state':'completed','checked_at_utc':datetime.now(timezone.utc).isoformat(),
         'season':'S23','event_date':'2026-11-03','review_source':review.relative_to(ROOT).as_posix(),
         'review_sha256':hashlib.sha256(review.read_bytes()).hexdigest(),
         'reviewed_games':3,'text_patches':0,'release_id':release,
         'published_counts':{'S21':122,'S22':148,'S23':90,'total':360},
         'database_backup_receipt':backup.relative_to(ROOT).as_posix(),
         'backup_catalog_valid':True,'restore_test_performed':False,
         'database_games':[i['database_receipt']['game'] for i in items],
         'ballots':7,'choices':54,
         'manual_bluffs':[{'bvid':bv,'seat':seat,'name':name,'success':False,'other_wolves':'no'}
                          for bv,seat,name in zip(BV,[6,2,5],['KS','徐言雨','彭彭'])],
         'new_players':[], 'missing_photos':[],
         'acceptance':{**summary,'old_games_compared':retained['old_games_compared'],
                       'old_game_differences':retained['differences'],
                       'special_browser_pages':site['browser_pages']},
         'validation':{'incremental_apply_and_bluffs':'64 passed','frontend_typecheck':'passed',
                        'frontend_production_build':'passed','new_game_desktop_mobile':'passed',
                        'wolf_partner_personal_ledger':site['wolf_partner_personal_result'],
                        'post_publish_formal_json_matches_accepted':True},
         'site_url':'http://127.0.0.1:3000','commit_and_push_performed':False}
write_json(BASE/'application_20261104.json',receipt)
analysis=read_json(BASE/'analysis.json')
analysis.update(database_written=True,publication=True,status='reviewed_applied_published',
                application_receipt='data/reports/S23/incremental/application_20261104.json',
                published_release_id=release)
write_json(BASE/'analysis.json',analysis)
sys.stdout.reconfigure(encoding='utf8')
print(json.dumps({k:receipt[k] for k in ['state','release_id','published_counts','ballots','choices','site_url']},ensure_ascii=False,indent=2))
