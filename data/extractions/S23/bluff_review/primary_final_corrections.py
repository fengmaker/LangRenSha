"""Source-bound primary corrections after checking continuation receipts."""
import json
from primary_continue import ROOT, quote


def load(part):
    path=ROOT/f'data/extractions/S23/bluff_review/parts/audit_{part}.json'
    return path,json.loads(path.read_text(encoding='utf-8'))


def write(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


p,d=load('e')
g=next(g for g in d['games'] if g['bvid']=='BV1CAeA6qErr')
b=g['bvid']
for key in ['first_day_window','frame_selection']:
    g[key]['basis']='1041.24秒首日天亮，3、4、6、7号发言；1297秒在7号末段，1303.81秒1号自爆中断。次日9号直接自爆，1494.53秒法官宣布警徽流失；终盘3516.95/3526.34秒再次确认1号→9号顺序。'
notes={
 1:'1号首日尚未轮到本人话轮，在7号发言中直接自爆；随后已出局。3161秒别人说“一号玩家直接选择自爆”是在回顾首日，不是1号第二次自爆。出局前无本人信息神自称或报验。',
 2:'2号首日未轮到本人发言就由1号自爆中断，次日9号再爆；第三天本人明确自称白神，讨论10号女巫和狼坑。没有本人预言家/通灵师自称或报验，不能把4号猎人的话归2号。',
 5:'5号首日在警下，1号首日、9号次日连续自爆前没有本人话轮；第三天本人讨论3号出局身份、认可10号女巫，结束明确自称平民。无本人信息神起跳。',
 9:'9号首日在警下，1号自爆前没有本人话轮；次日9号直接自爆。终盘明确1号首日、9号次日自爆，不能把夜间预判9号将自爆当成首日已发生。出局前无本人信息神起跳。',
}
for a in g['assessments']:
    a['decision_note']=notes[a['seat']]
    images=[e for e in a['evidence'] if e['kind']=='video_frame']
    evidence=[quote(b,1303.81,1316,'首日1号自爆，转入夜间。'),
              quote(b,1488.77,1516,'次日9号自爆，警徽流失，公布死亡后入夜。'),
              quote(b,3513.51,3528.56,'终盘明确首日1号、次日9号的自爆顺序。')]
    if a['seat']==2:
        evidence += [quote(b,1936.95,1950,'正式交给2号后，本人自称白神。'),quote(b,1992.59,2036.2,'2号完整话轮末段仍是白神视角，之后4号另起猎人话轮。')]
    elif a['seat']==5:
        evidence += [quote(b,2193.5,2228,'5号本人首轮开头，分析他人身份并认10女巫。'),quote(b,2349.88,2379,'5号本人末段认10女巫、自称平民。')]
    a['evidence']=evidence+images
write(p,d)

p,d=load('f')
g=next(g for g in d['games'] if g['bvid']=='BV1V8af6zE56')
b=g['bvid']
for a in g['assessments']:
    images=[e for e in a['evidence'] if e['kind']=='video_frame']
    for e in images:
        if e['frame_time_ms']==1600000:
            e['text']='1600秒首日警上末位2号话轮。3号章亿阳侧栏验2金水；10号陈明峻狼人侧栏验11金水、警徽流3-4，原话反复为3/1顺验，保留两者差异。2/5号无本人查验摘要。'
        elif e['frame_time_ms']==1550000:
            e['text']='1550秒在3号本人警上话轮，3号侧栏验2金水；1/5顺验由本人原话核实，不能挪用7/8号侧栏警徽流。'
    if a['seat']==10:
        a.update(decision='yes',claimed_role='预言家',claim_day=1,first_day_claim=True,
                 decision_note='10号本人首日警上1110.62–1198.99秒反复自称预言家、报验11金水并留3/1顺验；主帧10号侧栏也有验11金水。原复核误读其警下退水后的平民自称，漏掉此前实际起跳，现改为是；后续退水不抹去尝试。侧栏流3-4与本人反复说3/1不一致，按本人原话说明。')
        a['evidence']=[quote(b,1110.62,1155.35,'本人报验11金水、自称预言家并留3/1顺验。'),
                       quote(b,1177.62,1199.1,'本人强调不是骗退水，明确预言家验11金水，重复3/1顺验。')]+images
    elif a['seat']==3:
        a['decision_note']='3号本人首日警上报验2号金水，称“单边预言家”并留1/5顺验；3号侧栏验2金水与原话互证。警徽流采用本人原话，不能挪用其他座位的1/5侧栏；后续仍维持自己预言家视角。'
    for e in a['evidence']:
        if e['kind']=='video_frame':
            e['text']=next((im['text'] for im in images if im['source_path']==e['source_path']),e['text'])
write(p,d)

p,d=load('g')
g=next(g for g in d['games'] if g['bvid']=='BV1vMpm6QEdM')
a=next(a for a in g['assessments'] if a['seat']==4)
a['decision_note']='4号首日警下2672.92–2848.22秒实际有完整本人话轮，分析5号、解释投6号后弃票，最后自称好人；原记录“首日没有本人话轮”已纠正。第三天本人认狼、谈刀后自爆，全程未认领信息神或报自己的查验。'
a['evidence']=[quote(g['bvid'],2672.92,2848.3,'4号完整首日警下话轮，自称好人、分析别人。'),
               quote(g['bvid'],5143.62,5198,'第三天本人认狼谈刀、自爆，没有信息神自称。')]+[e for e in a['evidence'] if e['kind']=='video_frame']
g=next(g for g in d['games'] if g['bvid']=='BV1i6J163EnN')
a=next(a for a in g['assessments'] if a['seat']==12)
a['decision_note']=a['decision_note'].replace('这是一号位物理狼','这是12号物理狼')
g=next(g for g in d['games'] if g['bvid']=='BV1i6J163Ees')
a=next(a for a in g['assessments'] if a['seat']==8)
a['evidence']=[quote(g['bvid'],1851.75,1964.36,'8号本人实际话轮开头至女巫自称、救9；前一位7号的验4/12不能归给8号。')]+[e for e in a['evidence'] if e['kind']=='video_frame']
write(p,d)

p,d=load('h')
g=next(g for g in d['games'] if g['bvid']=='BV1nJer6gEkx')
evidence=[quote(g['bvid'],2239.35,2241,'法官明确本局警徽流失。'),
          quote(g['bvid'],4299.9,4306.69,'终盘说明延期竞选吞毒自爆、警徽流失。')]
g['result_review']={'badge':'lost','note':'正式档案未列明警徽流失；法官及终盘原文均明确流失。仅补悍跳成功判定，原始对局档案不改写。','evidence':evidence}
for a in g['assessments']:
    if a['decision']=='yes':
        a['evidence']=[e for e in a['evidence'] if not(e.get('interpretation','').startswith('补充警徽结果：'))]
        a['evidence'] += [dict(e,interpretation='补充警徽结果：'+e['interpretation']) for e in evidence]
write(p,d)
print('Corrected continuation receipts E/F/G/H against source and original frames.')
