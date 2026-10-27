"""Local OCR support for S23 candidate reviews; never changes game records."""
import csv
import json
from pathlib import Path
import sys

from collect_bilibili_audio import save_json
from read_s22_frame_labels import analyze_frame, norm, run_pass

ROOT=Path(__file__).resolve().parents[1]
ALIAS=ROOT/'data/weibo/2026-05-26_2026-10-20/参赛名单/人名去重_照片映射.csv'


def main():
    import cv2
    from rapidocr import RapidOCR
    aliases={}
    with ALIAS.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('赛季')!='S23' or row.get('原人工确认状态') not in {'确认无误','已修正'}:
                continue
            canonical=row['去重后姓名'].strip()
            for key in ['原图名字','复核行名字','去重后姓名']:
                if row.get(key):aliases.setdefault(norm(row[key]),set()).add(canonical)
    plan=json.loads((ROOT/'data/reports/S23_逐局复核计划.json').read_text(encoding='utf-8'))
    engine=RapidOCR()
    for entry in plan['entries']:
        if entry['phase']!='regular':continue
        folder=ROOT/f'data/extractions/S23/game_reviews/{entry["bvid"]}'
        out=folder/'screen_ocr.json'
        if out.exists():continue
        dossier=json.loads((folder/'baseline.dossier.json').read_text(encoding='utf-8'))
        frame=entry['frame'];path=ROOT/frame['frame_path']
        value=analyze_frame(path,frame['frame_time_ms'],entry['bvid'],dossier,engine,aliases,aliases,ALIAS)
        # Extra adjacent role lanes retain the broadcaster's actual-role labels and vote markers.
        image=cv2.imread(str(path));height,width=image.shape[:2];lanew=round(width*.17)
        role_lines=[]
        for x in [0,width-lanew]:
            crop=cv2.resize(image[:,x:x+lanew],None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
            lines,_=run_pass(engine,crop,'screen_role_and_vote_lane_x2',x0=x,scale=2)
            role_lines.extend(lines)
        value['scope']='S23_screen_candidates_only'
        value['role_and_vote_ocr_lines']=role_lines
        value['note']='OCR仅作定位；姓名/实际底牌/票型需要逐局与画面和复盘交叉核对，黄色自称和解说文字不能当底牌。'
        save_json(out,value)
        print(f"#{entry['index']} {entry['bvid']}: names {sum(bool(s.get('name')) for s in value['seats'])}/12",flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
