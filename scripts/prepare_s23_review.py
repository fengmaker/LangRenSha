"""Prepare evidence packets and candidate dossiers; never import game facts."""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import batch_s22 as legacy
from board_catalog import BOARD_CODES
from collect_bilibili_audio import save_json
from game_records import empty_event
from season_naming import digest
from voting_records import extract as extract_votes

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'data/extractions/S23/game_reviews'
PLAN = ROOT/'data/reports/S23_逐局复核计划.json'


def segments(path: Path) -> list[dict]:
    value=json.loads(path.read_text(encoding='utf-8'))
    result=[]
    for i,row in enumerate(value.get('segments',value.get('body',[]))):
        if 'start_ms' in row:
            start,end,text=row['start_ms'],row['end_ms'],row.get('text','')
        elif 'start' in row:
            start,end,text=round(row['start']*1000),round(row['end']*1000),row.get('text','')
        else:
            start,end,text=round(row['from']*1000),round(row['to']*1000),row.get('content','')
        if text.strip():result.append({'index':i,'start_ms':start,'end_ms':end,'text':text})
    return result


def schedule_for(date):
    path=ROOT/'data/weibo/2026-05-26_2026-10-20/比赛排班.csv'
    with path.open(encoding='utf-8-sig',newline='') as stream:
        found=[r for r in csv.DictReader(stream) if r['赛季']=='S23' and r['比赛日期']==date]
    return found


def prepare():
    plan=json.loads((ROOT/'data/indexes/S23_采集计划.json').read_text(encoding='utf-8'))
    media=json.loads((ROOT/'data/reports/S23_转写入库验收.json').read_text(encoding='utf-8'))
    sources={r['bvid']:r for r in media['items']}
    frames=json.loads((ROOT/'data/reports/S23_发言截图进度.json').read_text(encoding='utf-8'))['items']
    with (ROOT/'data/seasons/S23/S23_中文优先复核目录.csv').open(encoding='utf-8-sig',newline='') as stream:
        captions={r['BVID']:r for r in csv.DictReader(stream)}
    entries=[]
    for original in plan['entries']:
        if original['labels']['phase_candidate'] != 'regular':
            continue
        bvid=original['bvid'];labels=original['labels'];source=ROOT/sources[bvid]['transcript']
        caption=captions[bvid]
        # Use the exact subtitle JSON for platform tracks; its body preserves native timestamps.
        if sources[bvid]['kind']=='platform_chinese_subtitle':source=ROOT/caption['中文字幕原件']
        rows=segments(source)
        code=BOARD_CODES.get(labels['board_candidate'])
        entry={**original,'season':'S23','date':labels['event_date_candidate'],
               'phase':labels['phase_candidate'],'board_name':labels['board_candidate'],'board':code,
               'game_number':labels['game_number_candidate'],'episode':labels['issue_candidate'],
               'source_path':source.relative_to(ROOT).as_posix(),'source_sha256':digest(source),
               'transcript_origin':'本地全文转写' if sources[bvid]['kind']=='local_full_audio' else '平台中文字幕',
               'audio_path':caption['音频文件'],'frame':frames[bvid],
               'output_dir':f'data/games/S23/{labels["event_date_candidate"]}_g{labels["game_number_candidate"] or 0:02d}_{bvid}'}
        folder=BASE/bvid;folder.mkdir(parents=True,exist_ok=True)
        location=legacy.locate_recap(rows,original['duration_seconds']*1000)
        recap=location['segments']
        extracted=legacy.extract_game_recap(recap,entry['board_name']) if recap else {'seats':[],'rounds':[],'winning_faction':None,'issues':['集中复盘需进一步定位']}
        if code:
            dossier,issues,unmapped=legacy.build_dossier(entry,extracted)
            dossier['season']='S23'
        else:
            dossier={'slug':f'bili-{bvid}-p01-g{entry["game_number"] or 0:02d}','season':'S23',
                     'date':entry['date'],'phase':entry['phase'],'episode':entry['episode'],
                     'game_number':entry['game_number'],'board':'qingqiu_night' if '青丘' in entry['board_name'] else 'magic_duel',
                     'winner':extracted.get('winning_faction'),'roster':[],'commentators':[],'referee':None,
                     'seats':[{'seat':i,'name':None,'role':next((r.get('role') for r in extracted.get('seats',[]) if r['seat']==i),None),'faction':None,'learning_target':None,'learned_role':None} for i in range(1,13)],
                     'rounds':extracted.get('rounds',[]),'files':[]}
            issues=['S23新增版型：不得套用S22特殊技能规则，需核对当局播报与画面']
            unmapped=[]
        schedules=schedule_for(entry['date'])
        if len(schedules)==1:
            sch=schedules[0];dossier['roster']=[s.strip() for s in re.split('[、,，]',sch['选手']) if s.strip()]
            dossier['commentators']=[s.strip() for s in re.split('[、,，]',sch['解说']) if s.strip()];dossier['referee']=sch['法官'] or None
        votes,audit=extract_votes(rows,dossier,entry['source_path'])
        save_json(folder/'baseline.dossier.json',dossier)
        save_json(folder/'baseline.voting.json',votes)
        save_json(folder/'baseline.evidence.json',{'entry':entry,'recap_location':{k:v for k,v in location.items() if k!='segments'},
                   'recap_segments':recap,'issues':issues,'unmapped_events':unmapped,'voting_audit':audit,'schedules':schedules})
        # Focused evidence is a starting point; all original cues remain available via source_path.
        chosen=set()
        if recap:
            for i,r in enumerate(rows):
                if r['end_ms']>=recap[0]['start_ms']-8000 and r['start_ms']<=recap[-1]['end_ms']+8000:chosen.add(i)
        else:chosen.update(range(max(0,len(rows)-150),len(rows)))
        for i,r in enumerate(rows):
            t=r['text']
            judge=(len(t)<85 and re.search('投票结束|归票|投给|号.*(?:投|票)|(?:本局|本游戏|其他|其余).*上警|名玩家在警下|昨夜.*(?:死亡|倒牌|平安)|游戏结束|阵营.*获胜|开始复盘|进行复盘',t))
            claim=(len(t)<100 and re.search('我是.*(?:预言家|通灵师)|我跳(?:预言家|通灵师)|悍跳|汉跳|我验的|我验了|我查验',t))
            if judge or claim:
                chosen.update(range(max(0,i-1),min(len(rows),i+3)))
        lines=[f"原目录 #{entry['index']} {entry['title']}",f"BVID: {bvid}",f"source_path: {entry['source_path']}",f"source_sha256: {entry['source_sha256']}",
               f"截图: {frames[bvid]['frame_path']} @ {frames[bvid]['frame_time_ms']}ms",'本文件只是定位材料；需结合完整上下文核对。数字和说话人不得仅凭正则结论确认。','',
               '【基线候选，不是已核实事实】',json.dumps({'seats':dossier['seats'],'rounds':extracted.get('rounds'),'winner':dossier['winner'],'voting':votes},ensure_ascii=False),
               '','【按时间排序的复盘/投票/发言定位原句】']
        lines += [f"[{rows[i]['index']} {rows[i]['start_ms']}..{rows[i]['end_ms']}] {rows[i]['text']}" for i in sorted(chosen)]
        (folder/'evidence_packet.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        save_json(folder/'entry.json',entry)
        entries.append(entry)
        print(f"#{entry['index']} {bvid}: recap {len(recap)} cues; focus {len(chosen)} / {len(rows)}",flush=True)
    result={'season':'S23','created_at_utc':datetime.now(timezone.utc).isoformat(),'entries':entries,
            'scope':dict(Counter(e['phase'] for e in entries)),'excluded_showmatches':12,'game_database_writes':False,
            'reviewer':'ai','human_confirmation_required_before_formal_import':True}
    save_json(PLAN,result)
    return {'entries':len(entries),'scope':result['scope'],'plan':PLAN.relative_to(ROOT).as_posix()}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(prepare(),ensure_ascii=False,indent=2))
