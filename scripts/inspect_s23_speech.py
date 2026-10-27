"""Locate numbered speech handoffs for AI inspection; no speaker facts imported."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

from prepare_s23_review import segments

ROOT=Path(__file__).resolve().parents[1]
NUMBER=r'(?:1[0-2]|[1-9]|十二|十一|十|[一二三四五六七八九])'
CALL=re.compile(rf'(?:请|有请)?(?P<seat>{NUMBER})号(?:玩家|选手|的)?(?:请|有请|开始|继续|进行)(?:做|进行)?发言')
CN={'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}


def windows(rows):
    calls=[]
    for i,row in enumerate(rows):
        text=row['text']
        if len(text)>60 or re.search('如果|因为|觉得|当时|昨天|昨天|明天|他说|说过',text):continue
        match=CALL.search(text)
        if match:
            value=match['seat'];seat=int(value) if value.isdigit() else CN[value]
            calls.append((i,seat))
    output=[]
    for j,(i,seat) in enumerate(calls):
        stop=calls[j+1][0] if j+1<len(calls) else len(rows)
        for k in range(i+1,stop):
            if re.fullmatch(r'(?:所有|各位|全体)?(?:玩家)?(?:发言结束|天黑请闭眼|请做好投票准备)[，。！!\s]*',rows[k]['text']):stop=k+1;break
        block=rows[i:stop]
        output.append({'seat':seat,'start_ms':rows[i]['start_ms'],'end_ms':block[-1]['end_ms'],
                       'instruction':rows[i]['text'],'segments':block,'attribution':'candidate_from_explicit_handoff'})
    return output


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('bvid');parser.add_argument('--seat',type=int);parser.add_argument('--before-ms',type=int);parser.add_argument('--limit',type=int,default=3);args=parser.parse_args()
    entry=json.loads((ROOT/f'data/extractions/S23/game_reviews/{args.bvid}/entry.json').read_text(encoding='utf-8'))
    found=[w for w in windows(segments(ROOT/entry['source_path'])) if (args.seat is None or w['seat']==args.seat) and (args.before_ms is None or w['start_ms']<args.before_ms)]
    for block in found[:args.limit]:
        print(f"\nSEAT {block['seat']} {block['start_ms']}..{block['end_ms']} {block['instruction']}")
        for row in block['segments']:print(row['start_ms'],row['text'])
