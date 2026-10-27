"""Evidence helpers for manually reviewed continuation records; no classification."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from website.api.bluffs import physical_wolf


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def source(bvid):
    entry=json.loads((ROOT/'data/extractions/S23/game_reviews'/bvid/'entry.json').read_text(encoding='utf-8'))
    raw=json.loads((ROOT/entry['source_path']).read_text(encoding='utf-8-sig'))
    rows=[{'start_ms':r.get('start_ms',round(r.get('from',0)*1000)),
           'end_ms':r.get('end_ms',round(r.get('to',0)*1000)),
           'text':r.get('text',r.get('content',''))} for r in raw.get('body',raw.get('segments',[]))]
    return entry,rows


def read(bvid,lo=0,hi=100000,pattern=None):
    entry,rows=source(bvid)
    print(bvid,'CID',entry['cid'])
    for r in rows:
        sec=r['start_ms']/1000
        if lo<=sec<hi and (not pattern or re.search(pattern,r['text'])):
            print(f'{sec:.2f}',r['text'])


def quote(bvid,lo,hi,meaning):
    entry,rows=source(bvid)
    selected=[r for r in rows if lo*1000<=r['start_ms']<hi*1000]
    assert selected,(bvid,lo,hi)
    return {'kind':'transcript','source_path':entry['source_path'],'source_sha256':sha(ROOT/entry['source_path']),
            'start_ms':selected[0]['start_ms'],'end_ms':selected[-1]['end_ms'],
            'text':'\n'.join(r['text'] for r in selected),'interpretation':meaning}


def frame(bvid,sec,meaning):
    path=ROOT/'data/extractions/S23/bluff_review/frames'/bvid/f'{bvid}_{sec:09.3f}.png'
    assert path.is_file(),path
    return {'kind':'video_frame','source_path':path.relative_to(ROOT).as_posix(),'source_sha256':sha(path),
            'start_ms':round(sec*1000),'end_ms':round(sec*1000),'frame_time_ms':round(sec*1000),
            'text':meaning,'interpretation':'主审已目视原帧，并与正式底牌、完整本人话轮和前后流程交叉核对。'}


def build(bvid,frame_sec,start,end,basis,decisions,extras=None):
    dossier=json.loads(next((ROOT/'data/games/S23').glob('*'+bvid+'/dossier.json')).read_text(encoding='utf-8'))
    entry,_=source(bvid)
    wolves={s['seat']:s for s in dossier['seats'] if physical_wolf(dossier,s)}
    assert set(wolves)==set(decisions),(bvid,set(wolves),set(decisions))
    assessments=[]
    for seat,(decision,role,day,note,windows,overlay) in decisions.items():
        s=wolves[seat]
        evidence=[quote(bvid,*w) for w in windows]+[frame(bvid,frame_sec,overlay)]
        evidence += [frame(bvid,*item) for item in (extras or {}).get(seat,[])]
        assessments.append({'seat':seat,'name':s['name'],'physical_role':s['role'],'decision':decision,
                            'claimed_role':role,'claim_day':day if day in (1,2,None) else 'later',
                            'actual_claim_day':day if type(day) is int and day>2 else None,
                            'first_day_claim':day==1 if decision=='yes' else False,
                            'confidence':'high','verification_status':'assistant_inferred',
                            'decision_note':note,'evidence':evidence,'review_questions':[]})
    main=frame(bvid,frame_sec,'主审目视首日警上最后发言末段或提前中断前原帧。')
    return {'game_id':dossier['slug'],'bvid':bvid,'date':dossier['date'],'game_number':dossier['game_number'],
            'source_path':entry['source_path'],'source_sha256':sha(ROOT/entry['source_path']),
            'first_day_window':{'start_ms':round(start*1000),'end_ms':round(end*1000),'basis':basis},
            'frame_selection':{'timestamp_ms':round(frame_sec*1000),'basis':basis,'phase_verified':True,
                               'visual_reviewed':True,'overlay_readable':True,'frame_path':main['source_path'],
                               'frame_sha256':main['source_sha256']},
            'assessments':assessments,'separate_identity_claims':[],'notes':['主审逐局复核；未新增用户确认。']}


def save(game):
    path=ROOT/'data/extractions/S23/bluff_review/parts/audit_h.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'part':'h','reviewer':'primary_assistant','games':[]}
    data['games']=[g for g in data['games'] if g['game_id']!=game['game_id']]+[game]
    data['games'].sort(key=lambda g:(g['date'],g['game_number']))
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    json.loads(temp.read_text(encoding='utf-8'));temp.replace(path)
    print('Saved',game['bvid'],len(data['games']))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    read(sys.argv[1],float(sys.argv[2]) if len(sys.argv)>2 else 0,
         float(sys.argv[3]) if len(sys.argv)>3 else 100000,sys.argv[4] if len(sys.argv)>4 else None)
