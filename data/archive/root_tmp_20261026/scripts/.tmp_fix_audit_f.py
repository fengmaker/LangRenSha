import json
from pathlib import Path
p=Path('data/extractions/S23/bluff_review/parts/audit_f.json')
s=p.read_text(encoding='utf-8')
if s.endswith(chr(92)+'n'): s=s[:-2]
d=json.loads(s)
g=next(g for g in d['games'] if g['bvid']=='BV1RPaW6zEg8')
main='1190.000s处于首日警上末位发言结束前；逐席读取侧栏：7号JY为“验10平民、警徽流5-12”；11号徐言雨为“验10金水、警徽流12-3”。1/8/12号侧栏未显示自己的预言家或通灵师验人/警徽流。'
extra='400.000s徐言雨（11号）本人正在首日警上发言；其侧栏记录“验10金水、警徽流12-3”，与385.96s本人原话相符。'
for a in g['assessments']:
    if a['seat']==11:
        a['decision_note']='11号在本人首日警上话轮先报10号为金水，安排警徽流，并明确说“无论如何我都会自己跳的”。1190.000s末位发言前截图中，逐席核准11号徐言雨侧栏为“验10金水、警徽流12-3”；不能把7号JY的“验10平民、警徽流5-12”误归给11号。400.000s另帧显示徐言雨本人正在发言。本人原话、话轮画面和11号侧栏互相印证，计为首日通灵师悍跳。'
    for e in a['evidence']:
        if e.get('kind')=='video_frame':
            if e.get('frame_time_ms')==1190000:
                e['text']=main
                e['interpretation']='已直接目视并逐席定位原帧：7号与11号各自侧栏已分别核对，11号验10金水/警徽流12-3，7号验10平民/警徽流5-12。'
            elif e.get('frame_time_ms')==400000:
                e['text']=extra
                e['interpretation']='已直接目视原帧：中心姓名牌为徐言雨，和右侧11号座位对应；其本人处于说话状态。'
        if e.get('kind')=='transcript':
            continue
    if a['seat']!=11:
        for e in a['evidence']:
            if e.get('kind')=='video_frame' and e.get('frame_time_ms')==1190000:
                e['text']=main
                e['interpretation']='已直接目视并逐席定位原帧：7号与11号各自侧栏已分别核对，11号验10金水/警徽流12-3，7号验10平民/警徽流5-12。'
d['games']=[g if g['bvid']=='BV1RPaW6zEg8' else g for g in d['games']]
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
print('corrected mappings; game count',len(d['games']))
