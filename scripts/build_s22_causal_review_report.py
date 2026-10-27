"""Publish the disposition of every original flag and the residual manual queue."""
from __future__ import annotations
import csv
import json
import sys

import batch_s22 as batch
from causal_voting_review import REVIEW


def build():
    accepted = batch.read_json(REVIEW)
    baseline = batch.read_json(REVIEW.parent / 'baseline.json')
    current = batch.read_json(batch.REPORT_DIR / 'S22_投票逐局核对.json')
    state = batch.load_state()
    expected = {q['id'] for i in baseline['items'] for q in i['questions']}
    decisions = [d for i in accepted['items'] for d in i['decisions']]
    assert len(decisions) == len(expected) == len({d['question_id'] for d in decisions})
    assert {d['question_id'] for d in decisions} == expected
    unresolved = {d['question_id'] for d in decisions if not d['resolved']}
    questions = [q for i in current['items'] for q in i['questions']]
    assert {q['id'] for q in questions} == unresolved, '生成的待处理清单与逐项裁定不一致，须继续核查新问题'
    result = {'generated_at': batch.now(), 'games_reviewed':len(accepted['items']),
              'original_questions':len(expected), 'resolved':sum(d['resolved'] for d in decisions),
              'manual_required':len(unresolved), 'human_confirmed':sum(bool(d.get('human_reviewed')) for d in decisions),
              'method':'整局转写、因果推断、独立原音频重转写、必要的原视频画面核对及逐项用户人工确认',
              'human_reviewed':False, 'items':accepted['items'], 'manual_questions':questions}
    batch.atomic_json(batch.REPORT_DIR / 'S22_逐项因果复核.json', result)
    lines = [f"本轮复核{len(accepted['items'])}局、{len(expected)}项，解决{result['resolved']}项，仍需人工复核{len(unresolved)}项。",
             '', f"其中{result['human_confirmed']}项由用户人工确认；AI推断、原句与人工确认分别保留。", '', '## 必须人工复核', '']
    if not unresolved:
        lines.extend(['无。最后一项8月18日第3局第4天票型已由用户确认：1、4、6、7、8、9号投12号，12号投6号。', ''])
    with (batch.ROOT / 'data/exports/S22_必须人工复核.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['比赛日期','局次','BVID','游戏日','问题','仍无法确认的原因','原视频','问题ID'])
        for item in accepted['items']:
            entry = state['items'][item['bvid']]
            for d in item['decisions']:
                if d['resolved']:
                    continue
                q=d['original_question']
                ms=min((e['start_ms'] for e in d.get('media_evidence',[]) if e.get('start_ms') is not None),default=0)
                url=f"https://www.bilibili.com/video/{item['bvid']}/?t={ms//1000}"
                reason=d.get('residual_reason') or d['reason']
                writer.writerow([entry['date'],entry['game_number'],item['bvid'],q['day'],q['title'],reason,url,d['question_id']])
                lines.extend([f"- {entry['date']} 第{entry['game_number']}局，第{q['day']}天：{d['conclusion']}",f"  {reason} [打开原视频]({url})",''])
    lines.extend(['## 逐项结论',''])
    for item in accepted['items']:
        entry=state['items'][item['bvid']]
        lines.extend([f"### {entry['date']} 第{entry['game_number']}局 · {item['bvid']}",''])
        for d in item['decisions']:
            label='用户人工确认' if d.get('human_reviewed') else '已解决' if d['resolved'] else '必须人工'
            lines.extend([f"- **{label}**：{d['conclusion']}（置信度：{d['confidence']}）",f"  {d['reason']}",''])
    (batch.REPORT_DIR/'S22_逐项因果复核.md').write_text('\n'.join(lines),encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ('items','manual_questions')}


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(build(),ensure_ascii=False))
