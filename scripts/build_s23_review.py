"""Assemble S23 AI candidates and a local human-review workspace; no DB import."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from collect_bilibili_audio import save_json
from season_naming import digest

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from board_config import load_template
EXPORT=ROOT/'data/exports'
from s23_effective_game import load_effective_games, candidate_values, file_url


def build(require_complete=False):
    loaded = load_effective_games(require_complete=require_complete)
    games, missing = loaded['games'], loaded['missing']
    primary_notes, checkpoint = loaded['primary_notes'], loaded['checkpoint']
    questions = []
    EXPORT.mkdir(parents=True,exist_ok=True)
    for g in games:
        entry=g['entry'];out=ROOT/entry['output_dir'];out.mkdir(parents=True,exist_ok=True)
        for name, value in candidate_values(g).items():
            save_json(out/name, value)
        g['candidate_sha256']=digest(out/'dossier.candidate.json')
        g['dossier_url']=file_url((out/'dossier.candidate.json').relative_to(ROOT).as_posix())
        for proof in walk_evidence(g['review']):
            if isinstance(proof.get('source_path'),str):proof['file_url']=file_url(proof['source_path'])
        for proof in walk_evidence(g['endgame']):
            proof['file_url']=file_url(proof['source_path'])
        for proof in walk_evidence(g['vote_control']):
            proof['file_url']=file_url(proof['source_path'])
        for i,q in enumerate(g['review'].get('human_questions',[])):
            questions.append({'日期':entry['date'],'局次':entry['game_number'],'版型':entry['board_name'],'BVID':entry['bvid'],
                              '轮次':q.get('round'),'阶段':q.get('phase'),'日夜':q.get('phase_label'),
                              '问题ID':q.get('id',str(i)),'字段':q.get('field'),'问题':q.get('question'),
                              '选项':' | '.join(q.get('options',[])),'原因':q.get('reason'),'证据':json.dumps(q.get('evidence',[]),ensure_ascii=False)})
    snapshot=hashlib.sha256('\n'.join(g['entry']['bvid']+g['entry']['source_sha256']+g['candidate_sha256']+
                                    hashlib.sha256(json.dumps(g['voting'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['endgame'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['vote_control'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()+
                                    hashlib.sha256(json.dumps(g['review'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                                    for g in games).encode()).hexdigest()
    labels={}
    for path in (ROOT/'config/board_templates').glob('*.json'):
        board=load_template(path.stem,ROOT)
        for phase in ['night','day']:
            for slot in board.get(phase+'_slots',[]):labels[slot['code']]=slot['label']
    labels.update({'fox_mark':'九尾狐标记','fox_hunt':'九尾狐猎杀时刻','baize_purge':'白泽清除标记',
                   'baize_inherit':'白泽传承','wolf_sorcerer_exchange':'狼术师交换','fox_knife':'九尾狐带刀',
                   'nine_tail_mark':'九尾狐标记','nine_tail_hunt':'九尾狐猎杀时刻','baize_clear':'白泽清除标记'})
    labels.update({'whiteze_clear_mark':'白泽清除标记','whiteze_clear':'白泽清除标记',
                   'nine_tail_kill':'九尾狐猎杀结算','nine_tail_skill':'九尾狐猎杀时刻',
                   'nine_tail_vote_mark':'九尾狐警徽票标记','game_end':'游戏结束',
                   'magic_duel_wolf_sorcerer_swap':'狼术师交换','magic_duel_magician_swap':'魔术师交换',
                   'disqualification':'违规判离（DQ）','sheriff_vote':'警长竞选投票'})
    labels.update({'concession':'交牌认输','werewolf_surrender':'狼人交牌','treasure_master_change':'盗宝大师切换身份',
                   'magician_death_exchange':'魔术师出局交换','sorcerer_exchange':'狼术师交换','game_end':'游戏结束'})
    summary={'planned':75,'ai_reviewed':len(games),'human_questions':len(questions),
             'games_with_human_questions':sum(bool(g['review'].get('human_questions')) for g in games),
             'known_roles':sum(bool(s.get('role')) for g in games for s in g['dossier']['seats']),
             'named_seats':sum(bool(s.get('name')) for g in games for s in g['dossier']['seats']),
             'ballots':sum(len(g['voting'].get('ballots',[])) for g in games),
             'votes':sum(len(b.get('votes',[])) for g in games for b in g['voting'].get('ballots',[])),
             'wolf_rush_phases':sum(len(g['endgame']['phases']) for g in games),
             'ai_followup_games':sum(bool(g['review'].get('open_ai_followups')) or g['review']['phase_review_counts']['unresolved']>0 for g in games),
             'phase_pending_items':sum(g['review']['phase_review_counts']['unresolved'] for g in games),
             'phase_pending_games':sum(g['review']['phase_review_counts']['unresolved']>0 for g in games),
             'phase_inferred_items':sum(g['review']['phase_review_counts']['inferred'] for g in games),
             'daily_audited_games':sum('daily_audit' in g['review'] for g in games),
             'unpublished_source_items':sum(g['review']['phase_review_counts'].get('not_observed',0) for g in games),
             'displayed_recap_segments':sum(len(g['transcript']) for g in games),
             'remaining_games':len(missing),'delivery_status':checkpoint.get('status','in_progress'),
             'excluded_showmatches':12,'formal_database_writes':False,
             'display_rule_inferences':sum(bool(e.get('inferred')) for g in games for r in g['presentation']['rounds'] for phase in ['night','day'] for e in r[phase]),
             'omitted_inapplicable_slots':sum(g['presentation']['omitted_events'] for g in games)}
    payload={'schema_version':1,'snapshot_id':snapshot,'generated_at_utc':datetime.now(timezone.utc).isoformat(),
             'summary':summary,'slot_labels':labels,'games':games}
    summary['delivery_status']='phase_gaps_pending' if summary['phase_pending_items'] else 'phase_reviewed_pending_user_confirmation'
    template=(ROOT/'scripts/templates/s23_review.html').read_text(encoding='utf-8')
    script=(ROOT/'scripts/templates/s23_review.js').read_text(encoding='utf-8')
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html=template.replace('__DATA__',encoded).replace('__SCRIPT__',script)
    html_path=EXPORT/'S23_逐局推导与复核.html';html_path.write_text(html,encoding='utf-8')
    fields=['日期','局次','版型','BVID','轮次','阶段','日夜','问题ID','字段','问题','选项','原因','证据']
    with (EXPORT/'S23_必须人工复核.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(questions)
    phase_rows=[]
    for g in games:
        for finding in g['review']['phase_findings']:
            if finding['status']!='unresolved':continue
            phase_rows.append({'日期':g['entry']['date'],'局次':g['entry']['game_number'],'版型':g['entry']['board_name'],
                               'BVID':g['entry']['bvid'],'轮次':finding['round'],'阶段':finding['phase'],
                               '日夜':finding['phase_label'],'问题ID':finding['id'],'字段':finding['field'],
                               '问题':finding['title'],'原因':finding.get('reasoning',''),
                               '证据':json.dumps(finding.get('evidence',[]),ensure_ascii=False)})
    with (EXPORT/'S23_日夜待核清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        fields2=['日期','局次','版型','BVID','轮次','阶段','日夜','问题ID','字段','问题','原因','证据']
        writer=csv.DictWriter(stream,fieldnames=fields2);writer.writeheader();writer.writerows(phase_rows)
    unpublished_rows=[]
    seen_unpublished={}
    for g in games:
        for finding in g['review']['phase_findings']:
            if finding['status']!='not_observed':continue
            field=str(finding.get('field') or '')
            kind='seer_check' if 'seer_check' in field else field
            key=(g['entry']['bvid'],finding['round'],finding['phase'],kind)
            number=len(unpublished_rows)+1
            duplicate=seen_unpublished.get(key)
            seen_unpublished.setdefault(key,number)
            proof=next((e for e in finding.get('evidence',[]) if isinstance(e.get('start_ms'),(int,float))),None)
            unpublished_rows.append({'序号':number,'日期':g['entry']['date'],'局次':g['entry']['game_number'],
                '版型':g['entry']['board_name'],'BVID':g['entry']['bvid'],'日夜':finding['phase_label'],
                '事项':finding['title'],'保留未知的内容':finding.get('conclusion',''),
                '原因':finding.get('reasoning',''),'备注':f'与第{duplicate}条重复（同一事项）' if duplicate else '独立事项',
                '视频定位':g['video_url']+(f'?t={int(proof["start_ms"]//1000)}' if proof else ''),
                '记录ID':finding['id']})
    with NamedTemporaryFile(mode='w',encoding='utf-8-sig',newline='',dir=EXPORT,suffix='.csv.tmp',delete=False) as stream:
        fields3=['序号','日期','局次','版型','BVID','日夜','事项','保留未知的内容','原因','备注','视频定位','记录ID']
        writer=csv.DictWriter(stream,fieldnames=fields3);writer.writeheader();writer.writerows(unpublished_rows)
        unpublished_temp=Path(stream.name)
    unpublished_csv=EXPORT/'S23_资料未公开清单.csv'
    unpublished_original_locked=False
    try:
        os.replace(unpublished_temp,unpublished_csv)
    except PermissionError:
        unpublished_original_locked=True
        unpublished_csv=EXPORT/'S23_资料未公开清单_更新.csv'
        os.replace(unpublished_temp,unpublished_csv)
        # Keep a usable export when a desktop editor denies writes/deletes
        # on the previous CSV. Every link in this page points to the new file.
        html=html.replace('S23_资料未公开清单.csv',unpublished_csv.name)
        html_path.write_text(html,encoding='utf-8')
    save_json(ROOT/'data/reports/S23/S23_日夜待核定位.json',{'generated_at_utc':payload['generated_at_utc'],
              'pending_items':summary['phase_pending_items'],'pending_games':summary['phase_pending_games'],
              'games':[{'bvid':g['entry']['bvid'],'date':g['entry']['date'],'game_number':g['entry']['game_number'],
                        'findings':g['review']['phase_findings']} for g in games],'formal_database_writes':False})
    save_json(ROOT/'data/reports/S23/S23_人员规范化依据.json',{'items':primary_notes})
    save_json(ROOT/'data/reports/S23/S23_结构规范化依据.json',{'games':[{'bvid':g['entry']['bvid'],'changes':g['review']['structural_normalizations'],'supplemental_events':g['supplemental_events']} for g in games]})
    report={**summary,'snapshot_id':snapshot,'generated_at_utc':payload['generated_at_utc'],
            'timings_seconds':loaded['timings_seconds'],'checked_games':len(games),
            'missing_ai_reviews':missing,'review_page':html_path.relative_to(ROOT).as_posix(),
            'human_review_csv':'data/exports/S23_必须人工复核.csv','phase_review_csv':'data/exports/S23_日夜待核清单.csv',
            'unpublished_review_csv':unpublished_csv.relative_to(ROOT).as_posix(),
            'unpublished_original_locked':unpublished_original_locked,
            'unpublished_unique_items':len(seen_unpublished),
            'candidate_dossiers':[g['entry']['output_dir']+'/dossier.candidate.json' for g in games]}
    save_json(ROOT/'data/reports/S23/S23_逐局复核进度.json',report)
    if require_complete and missing:raise ValueError(f'仍缺{len(missing)}局AI逐局复核，未报告完成')
    return report


def walk_evidence(value):
    if isinstance(value,dict):
        if 'source_path' in value and ('quote' in value or value.get('kind')=='video_frame'):yield value
        for child in value.values():yield from walk_evidence(child)
    elif isinstance(value,list):
        for child in value:yield from walk_evidence(child)


def build_one(bvid, *, require_complete=False):
    loaded = load_effective_games([bvid], require_complete=require_complete)
    if not loaded['games']:
        raise ValueError('尚缺逐局AI复核：' + bvid)
    game = loaded['games'][0]
    out = ROOT / game['entry']['output_dir']
    out.mkdir(parents=True, exist_ok=True)
    for name, value in candidate_values(game).items():
        save_json(out/name, value)
    return {'mode': 'partial', 'bvid': bvid, 'checked_games': 1,
            'candidate_dossiers': [game['entry']['output_dir']+'/dossier.candidate.json'],
            'dependency_bvids': loaded['dependency_bvids'],
            'timings_seconds': loaded['timings_seconds'], 'formal_database_writes': False}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-complete',action='store_true')
    parser.add_argument('--bvid',help='只生成该局候选，不重写全季页面、进度或验收报告')
    args=parser.parse_args()
    result=build_one(args.bvid,require_complete=args.require_complete) if args.bvid else build(args.require_complete)
    print(json.dumps({k:v for k,v in result.items() if k not in {'candidate_dossiers','missing_ai_reviews'}},ensure_ascii=False,indent=2))
