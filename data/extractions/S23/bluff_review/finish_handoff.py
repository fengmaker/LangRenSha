"""Record the completed, accepted S23 bluff publication without changing game facts."""
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from scripts.import_bluff_feedback import source_games
from website.api import bluffs, bluff_store, publisher


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    asset=ROOT/'website/assets/bluffs/S23.json'
    payload=json.loads(asset.read_text(encoding='utf-8'))
    acceptance=ROOT/'data/reports/S23_悍跳视频交叉复核验收_20261026.json'
    accepted=json.loads(acceptance.read_text(encoding='utf-8'))
    assert accepted['games_video_rechecked']==75 and not accepted['browser_errors']
    assert accepted['summary']==payload['summary']
    assert payload['summary']['assistant_pending']==0
    publication=bluff_store.publish_review('S23')
    assert publication['idempotent'], 'Must already be published and accepted'
    games=source_games('S23')
    items=bluffs.review_items(games,payload)
    questions=[{'review_id':r['review_id'],'date':r['date'],'game_number':r['game_number'],
                'seat':r['seat'],'name':r['name'],'questions':r['review_questions']}
               for r in items if r['requires_user_review']]
    assert not questions
    final_game=[r for r in items if r['bvid']=='BV1U3p86dEJY']
    assert next(r for r in final_game if r['seat']==10)['decision']=='no'
    assert next(r for r in final_game if r['seat']==6)['decision']=='yes'
    _,source_hash,_=publisher.load_release(ROOT,['S22','S23'])
    assert source_hash=='1c2312637b4dd6b89e365b122e8ef0f7f17e006e9691c5b53051a3c65a827925'
    with publisher._connect() as conn:
        active=conn.execute('SELECT r.id,r.source_hash FROM releases r JOIN active_release a ON a.release_id=r.id').fetchone()
    assert active['id']==accepted['game_release_unchanged'] and active['source_hash']==source_hash
    parts=ROOT/'data/extractions/S23/bluff_review/parts'
    report={
      'delivered_at_utc':datetime.now(timezone.utc).isoformat(),
      'status':'complete; all 75 games reviewed; user confirmed the final eulogy exclusion; no pending items',
      'website':'http://127.0.0.1:3000/seasons/S23/bluff-review',
      'offline_page':'data/exports/S23_悍跳推断与复核.html',
      'formal_games':75,'video_rechecked_games':75,'rechecked_wolf_seats':300,
      'summary':payload['summary'],'requires_user_judgment':questions,
      'pending_assistant_games':[],'pending_assistant_details':[],
      'part_receipts':{p.name:digest(p) for p in sorted(parts.glob('audit_*.json'))},
      'part_game_counts':{p.name:len(json.loads(p.read_text(encoding='utf-8'))['games']) for p in sorted(parts.glob('audit_*.json'))},
      'wip_notes':['A–H覆盖全部75局，原WIP文件只作历史线索，不参与完成数或统计。',
                   '未填写或未回复不视作用户确认；用户明确确认10月9日第三局10号遗言起跳不计入悍跳，该局6号悍跳保留。'],
      'final_user_decision':{'review_id':'BV1U3p86dEJY:10','decision':'no',
                             'quote':'10 月 9 日第三局，10 号遗言起跳是否计入悍跳  不计入，这局是6号悍跳'},
      'inference_version':payload['inference_version'],
      'bluff_publication_id':publication['publication_id'],
      'bluff_payload_hash':publication['payload_hash'],
      'publication_idempotency_verified':publication['idempotent'],
      'formal_release_unchanged':active['id'],'formal_source_hash_unchanged':source_hash,
      'S22_bluffs_unchanged':{'identified_bluffs':121,'successes':46,'pending':0},
      'acceptance_report':acceptance.relative_to(ROOT).as_posix(),
      'validation':{'backend_tests_passed':141,'next_production_build':'passed',
                    'browser_viewports':accepted['viewports'],'browser_errors':accepted['browser_errors'],
                    'original_frame_assets_verified':accepted['image_assets'],
                    'feedback_export':'offline and online passed; test drafts cleared'},
      'artifact_hashes':{p.relative_to(ROOT).as_posix():digest(p) for p in [asset,
          ROOT/'data/exports/S23_悍跳推断与复核.html',ROOT/'data/exports/S23_悍跳推断与复核.json',acceptance]},
      'primary_corrections':[
        {'bvid':'BV1NBhU68EUy','seat':4,'from':'uncertain','to':'no','reason':'首日未发言即8号爆，次日11号爆，夜死无遗言。'},
        {'bvid':'BV1VPaW66EZz','seat':11,'from':'uncertain','to':'no','reason':'在警下投票后，未轮到本人话轮即自爆。'},
        {'bvid':'BV1zmpB6PEcF','seat':1,'from':'yes','to':'no','reason':'通灵师自称实际来自11号话轮，1号本人站3、遗言认平民。'},
        {'bvid':'BV1ZmHX6iEcx','seat':6,'from':'yes','to':'no','reason':'假面板型侧栏未有通灵摘要，本人未发言即自爆。'},
        {'bvid':'BV1g1YU6kERd','seat':4,'from':'yes','to':'no','reason':'假设引语被误当本人预言家认领，实际本人自称平民、站1。'},
        {'bvid':'BV15PaW66EjW','seat':9,'reason':'D1/D2连续自爆，实际首次通灵师起跳为第三天。'},
        {'bvid':'BV1V8af6zE56','seat':10,'from':'no','to':'yes','reason':'根审补回本人1110–1199秒预言家起跳，后续退水不删除已实施尝试。'},
        {'bvid':'BV17QJh6qEid','seat':4,'to':'no','reason':'906秒验9为3号提前接话；本人解释、画面及侧栏均归3号。'},
        {'bvid':'BV1CAeA6qErr','reason':'修正首日1号、次日9号自爆顺序；补4号首日话轮；2号假跳白神、5号自称平民。'},
        {'bvid':'BV1vMpm6QEdM','seat':4,'reason':'补回首日警下2672–2848秒实际本人话轮，没有信息神起跳。'},
        {'bvid':'BV1i6J163Ees','seat':8,'reason':'删除误归8号的7号验4/12，改用8号本人女巫/银水9原话。'},
        {'bvid':'BV14sY36hEPC','reason':'法官及复盘明确警徽流失，独立补充成功判定。'},
        {'bvid':'BV1nJer6gEkx','reason':'法官及复盘明确警徽流失，独立补充成功判定。'},
      ],
    }
    path=ROOT/'data/reports/S23_悍跳本次交付_20261026.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':path.relative_to(ROOT).as_posix(),'summary':report['summary'],
                      'publication_id':publication['publication_id'],'idempotent':True},ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
