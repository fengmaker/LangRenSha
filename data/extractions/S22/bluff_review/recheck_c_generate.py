import json,re,pathlib
from collections import OrderedDict
ROOT=pathlib.Path('.')
WORK=ROOT/'data/extractions/S22/bluff_review'
dossiers=sorted((ROOT/'data/games/S22').glob('*/dossier.json'))
by_bv={}
for index,p in enumerate(dossiers,1):
 d=json.loads(p.read_text(encoding='utf-8'))
 m=re.search(r'BV[0-9A-Za-z]{10}',d['slug'])
 if m: by_bv[m.group(0)]=(index,p,d)
old={}
for fn in ['part_c.json','part_d.json','part_e.json']:
 part=json.loads((WORK/fn).read_text(encoding='utf-8'))
 for g in part['games']:
  for a in g.get('assessments',[]):
   if a.get('decision') in {'yes','uncertain'}:
    old[(g['bvid'],a['seat'])]=(g,a)

# Explicit first-day rechecks of old candidates.
updates={
 ('BV1hQ3t6hEbS',2):('no',None,None,'high','首日2号本人轮次说“我摸排盐杀的是3号和11号”，上下文是在描述对3/11的读牌，没有自称预言家/通灵师或建立验人、警徽流。'),
 ('BV1JNgj6gEaf',4):('uncertain','预言家',1,'low','4号首日只报“一金水”，紧接着说“白天验的就是那个装的那个样子”；现有上下文不能确认是在冒充夜验预言家还是描述白天信息，不能仅凭一个金水断言起跳。'),
 ('BV1JNgj6gEaf',7):('yes','预言家',1,'high','7号首日本人轮次直接说“我底牌是预言家”，并继续给出验人和警徽流，是明确第一人称预言家自称；物理底牌为狼人。'),
 ('BV1iDGK61E2z',6):('uncertain','预言家',1,'low','6号首日轮次中转写出“我可能是预言家这个位置啊”，但前后在讨论假设性狼队结构，且后续说自己偏向站边5号；不能仅凭这一句确认是实际起跳。'),
 ('BV1hFM26ME7o',10):('yes','通灵师',1,'high','10号首日PK发言直接说“我知道我是通灵师”。盗宝大师底牌后来获得通灵师技能，并不排除这次第一人称身份自称；该句足以计作跳通灵师。'),
 ('BV12Mur6nEns',8):('uncertain',None,None,'low','首日复盘片段只说“六八本来想悍跳”，这说明计划而非实际宣称；当前转写没能可靠锁定#8本人对应的首日完整发言窗口，不能据此判no。'),
 ('BV17f8g6BEFQ',3):('yes','通灵师',1,'high','3号首日被叫到发言后报告“验的四是平民”，结合随后警徽流及本人轮次，这是以通灵师身份起跳；复盘记载其在延期竞选时自爆。'),
 ('BV17f8g6BEFQ',5):('no',None,None,'high','首日竞选候选名单明确排除5号，随后由6号开始发言；5号在警上竞选阶段自爆前未取得本人发言轮次，不能仅凭自爆判悍跳。'),
 ('BV1tj8p6RE1V',3):('yes','通灵师',1,'high','3号在首日本人发言中明说“通灵师啊”，并报“我昨天验了一个守卫”；随后在首日自爆。'),
 ('BV1kG8A6dEye',1):('no',None,None,'high','首日1号尚未轮到发言便自爆；法官此前依次点名其他座位，没有1号的本人首日发言，复盘确认首日一号狼人自爆。'),
 ('BV1kG8A6dE7A',5):('yes','通灵师',1,'high','平票PK后法官叫5号发言，5号本人在该首日发言中说“其次我觉得我是通灵师”，构成明确身份自称。'),
 ('BV1jM8B6jEkF',3):('no',None,None,'high','3号首日未被法官叫到发言便举手自爆；转写记录自爆发生在警徽流开始讨论时，复盘也只记录3号狼人自爆，没有本人信息神自称。'),
 ('BV1jM8B6jEkF',4):('no',None,None,'high','4号首日自己的发言只说明上警原因与对其他玩家的判断，没有自称预言家/通灵师；次日延期竞选尚未轮到4号时5号先自爆并入夜。'),
}

# Resolve source files and subtitle rows for direct evidence and day boundaries.
def source_paths(bv,p,d):
    paths=[]
    for f in d.get('files',[]):
        if f.get('role') in {'subtitle','transcript'} and f.get('path'):
            paths.append(f['path'])
    paths += [x.as_posix() for x in (ROOT/'data/seasons/S22').rglob(f'*{bv}*本地全文转写_funasr.json')]
    paths += [(p.parent/'复核记录.json').as_posix(),(p.parent/'复盘原文.txt').as_posix()]
    seen=[]
    for path in paths:
        if path not in seen and (ROOT/path).is_file(): seen.append(path)
    return seen

def rows(path):
    f=ROOT/path
    if f.suffix.lower()=='.json':
        data=json.loads(f.read_text(encoding='utf-8-sig'))
        seq=data.get('body',data.get('segments',data.get('recap_segments',[])))
        return [{'start_ms':r.get('start_ms',round(r.get('from',0)*1000)),
                 'end_ms':r.get('end_ms',round(r.get('to',0)*1000)),
                 'text':r.get('text',r.get('content',''))} for r in seq]
    out=[]
    for line in f.read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'\[([\d.]+)[–—-]([\d.]+)\]\s*(.*)',line)
        if m: out.append({'start_ms':round(float(m[1])*1000),'end_ms':round(float(m[2])*1000),'text':m[3]})
    return out

def add_ev(evidence, path, start, end, text, kind, interp):
    ev={'kind':kind,'source_path':path,'start_ms':int(start),'end_ms':int(end),'text':text,'interpretation':interp}
    if not any((x.get('source_path'),x.get('start_ms'),x.get('text'))==(path,int(start),text) for x in evidence): evidence.append(ev)

def find_ev(bv, phrase, kind, interp, min_ms=0, max_ms=10**9, preferred=None):
    p,dix,d=by_bv[bv][1],by_bv[bv][0],by_bv[bv][2]
    paths=source_paths(bv,p,d)
    if preferred:
        paths=([preferred] if preferred in paths else [preferred])+[x for x in paths if x!=preferred]
    for path in paths:
        for r in rows(path):
            if min_ms<=r['start_ms']<=max_ms and phrase in r['text']:
                return {'kind':kind,'source_path':path,'start_ms':r['start_ms'],'end_ms':r['end_ms'],'text':phrase,'interpretation':interp}
    return None

def day_end(bv,p,d):
    paths=source_paths(bv,p,d)
    for path in paths:
        if not path.endswith('.json'): continue
        rr=rows(path)
        light=None
        for r in rr:
            t=r['text'].strip()
            if 250_000<=r['start_ms']<=2_000_000 and '天亮了' in t and any(x in t for x in ('321','4321','54321','432','天亮了。','天亮了')):
                # avoid casual commentary that merely says "天亮了"
                if len(t)<=35 or any(x in t for x in ('321','4321','54321')):
                    light=r['start_ms'];break
        if light is None: continue
        for r in rr:
            if r['start_ms']<=light or r['start_ms']-light>5_000_000: continue
            t=r['text']
            if '天黑请闭眼' in t or '天黑请别' in t:
                return r['end_ms']
    return None

# Recheck cases that were uncertain/ambiguous, and preserve previous clearly supported evidence.
for (bv,seat),(g,a) in list(old.items()):
    ev=[dict(x) for x in a.get('evidence',[]) if all(k in x for k in ('kind','source_path','start_ms','end_ms','text','interpretation'))]
    new=updates.get((bv,seat))
    if new:
        decision,claimed,claim_day,conf,note=new
        if (bv,seat)==('BV1kG8A6dE7A',5):
            e=find_ev(bv,'其次我觉得我是通灵师','speech','5号本人在PK后的首日发言中明确自称通灵师。',min_ms=1_900_000,max_ms=2_100_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV17f8g6BEFQ',3):
            e=find_ev(bv,'验的四是平民','speech','3号被明确叫到后在本人首日发言中报告查验；结合警徽流和该轮语境判为通灵师起跳。',min_ms=770_000,max_ms=850_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV1tj8p6RE1V',3):
            for phrase in ('通灵师啊','我昨天验了一个守卫'):
                e=find_ev(bv,phrase,'speech','3号首日本人轮次的直接通灵师自称与验人主张。',min_ms=1_250_000,max_ms=1_350_000)
                if e: ev.append(e)
        elif (bv,seat)==('BV1jM8B6jEkF',4):
            e=find_ev(bv,'上警是因为在警下投票压力太大了','speech','4号本人首日发言解释上警原因，没有自称信息神；其后延迟首轮在轮到4号前被5号自爆中断。',min_ms=1_140_000,max_ms=1_180_000)
            if e: ev.append(e)
            for phrase in ('由2号玩家开始逆序发言','5号玩家选择自爆'):
                e=find_ev(bv,phrase,'speech','次日延期的首轮竞选中先从2号逆序发言，5号在4号被叫到前自爆，故4号没有本人身份自称。',min_ms=1_770_000,max_ms=1_790_000)
                if e: ev.append(e)
        elif (bv,seat)==('BV1jM8B6jEkF',3):
            e=find_ev(bv,'就现在三举手自爆了','commentary','转写显示3号举手自爆时尚未出现其本人发言轮次；自爆不是信息神自称。',min_ms=1_400_000,max_ms=1_430_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV17f8g6BEFQ',5):
            e=find_ev(bv,'本局游戏除一号2号五号七号','speech','首日候选名单排除了5号，随后法官从6号开始发言；5号自爆前没有本人候选发言轮次。',min_ms=650_000,max_ms=675_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV1hFM26ME7o',10):
            e=find_ev(bv,'盗宝大师选择通灵师身份验证','recap','复盘明确本局盗宝大师10号选择通灵师身份验证，说明这是其真实获得的技能。',min_ms=3_870_000,max_ms=3_880_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV1iDGK61E2z',6):
            e=find_ev(bv,'比如说像战队我面或者怎么样找对手之类的','speech','该句紧接着“我可能是预言家这个位置啊”，但语境仍像条件/假设分析；无法仅凭转写确认起跳。',min_ms=1_530_000,max_ms=1_540_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV12Mur6nEns',8):
            # retain the plan-only commentary as the reason for unresolved status
            pass
        elif (bv,seat)==('BV1kG8A6dEye',1):
            e=find_ev(bv,'第一天白天一号狼人自爆入夜','recap','复盘确认1号首日自爆；逐段核对首日发言提示未发现1号本人起跳。',min_ms=4_930_000,max_ms=4_945_000)
            if e: ev.append(e)
        elif (bv,seat)==('BV1hQ3t6hEbS',2):
            if ev: ev[0]['interpretation']='2号被叫到的首日发言这句指向对3号、11号的摸排/判断，并非“我是预言家/通灵师”的本人身份宣称；首日其余话语也未形成验人+警徽流主张。'
        elif (bv,seat)==('BV1JNgj6gEaf',4):
            if ev: ev[0]['interpretation']='4号首日发言只有“一金水”这一短句；结合紧接着的“白天验的…”语境，不足以确认是夜验起跳还是转述/白天信息。'
            for phrase,interp,lo,hi in [
                ('4号玩家请发言','法官开始4号首日本人发言。',450_000,455_000),
                ('一金水','4号只报出“一金水”，孤句本身不能确认是否为预言家夜验身份主张。',450_000,456_000),
                ('白天验的就是那个装的那个样子','4号紧接着提到“白天验”，语境可能描述白天信息，需核对是否在冒充预言家。',455_000,462_000)]:
                e=find_ev(bv,phrase,'speech',interp,min_ms=lo,max_ms=hi)
                if e: ev.append(e)
        elif (bv,seat)==('BV1JNgj6gEaf',7):
            for phrase,interp,lo,hi in [
                ('7号玩家请发言','法官明确点名7号在首日发言。',1_170_000,1_190_000),
                ('我底牌是预言家','7号在本人首日轮次直接自称底牌为预言家。',1_180_000,1_200_000)]:
                e=find_ev(bv,phrase,'speech',interp,min_ms=lo,max_ms=hi)
                if e: ev.append(e)
        if decision=='uncertain':
            claim_bool=None
            if (bv,seat)==('BV12Mur6nEns',8):
                questions=['首日约1,300,000–1,550,000ms轮次：转写中只找到“六八本来想悍跳”的计划性评论，无法可靠将#8的首日完整发言轮次归属到一条带身份自称的语句；需用户核对该窗口是否有实际预言家/通灵师起跳。']
            elif (bv,seat)==('BV1iDGK61E2z',6):
                questions=['首日#6本人轮次1,469,680–1,673,000ms：“我可能是预言家这个位置啊”前后在分析假设性狼队结构，之后又说警上偏向站边5号；请回听确认这句是否为实际自称而非条件/转写歧义。']
            elif (bv,seat)==('BV1JNgj6gEaf',4):
                questions=['首日#4本人轮次451,860–459,830ms：原文先只有“一金水”，随后紧接“白天验的就是那个装的那个样子”；请核对整句是否在自称预言家并报告查验，还是在描述白天信息/转述他人，当前不足以确认悍跳。']
            else:
                questions=['首日#2本人轮次1,490,000–1,545,000ms：孤句“我自己预言家”与前后持续比较6/10两位预言家、并说“我是比较想认为6号”的站边语境不一致；视频确认是2号本人发言但未显示其建立验人/警徽流，请回听核对该孤句是否ASR识别错误或实际起跳。']
        else:
            claim_bool=claim_day is not None
            questions=[]
        a2={'seat':seat,'name':a['name'],'physical_role':a['physical_role'],'decision':decision,
            'claimed_role':claimed,'claim_day':claim_day,'first_day_claim':claim_bool,'confidence':conf,
            'evidence':ev,'review_questions':questions,'decision_note':note}
    else:
        decision=a['decision']; claimed=a.get('claimed_role'); claim_day=1 if decision=='yes' else None
        first=True if decision=='yes' else None
        conf=a.get('confidence','medium')
        if (bv,seat)==('BV12Mur6nEns',11): conf='high'
        if decision=='yes':
            note='首日本人发言或法官复盘交叉确认该狼人底牌在首日竞选中冒充预言家/通灵师；每玩家每局计一次。'
            # Specific direct first-day excerpts where the prior evidence relied only on recap/commentary.
            if bv=='BV1JNgj6gEkr': pass
            if (bv,seat)==('BV1JNgj6gEaf',7):
                note='7号在首日本人轮次直接说“我底牌是预言家”，并继续报验/警徽流；裁判复盘确认其物理底牌为狼人，虽然后日再次悍跳自爆，本证据已证明首日起跳。'
                e=find_ev(bv,'我底牌是预言家','speech','7号首日本人轮次的直接身份自称，后续接报验与警徽流。',min_ms=1_180_000,max_ms=1_200_000)
                if e: ev.append(e)
            if (bv,seat)==('BV1tj8p6RE2h',7):
                note='7号在8号被叫到前的本人发言中说“4号11号试验”并续称“4号11号验二金水”，结合本人“我是一个预言家”是明确首日悍跳。'
                for phrase in ('我是一个预言家','然后就4号11号试验啊','我觉得4号11号验二金水'):
                    e=find_ev(bv,phrase,'speech','7号首日本人轮次中的直接预言家身份自称与验人信息。',min_ms=780_000,max_ms=830_000)
                    if e: ev.append(e)
            if (bv,seat)==('BV12Mur6nEns',11):
                note='11号首日被法官点到发言后在本人轮次明确说“我是通灵师”，并报4号并非猎人/守卫等验人结果；直接转写与第三方称其悍跳相互印证。'
                for phrase in ('十一号大请发言','我是通灵师过十二号老次发言念的四号不是猎人'):
                    e=find_ev(bv,phrase,'speech','11号首日本人发言轮次，直接确认其自称通灵师并报告验人。',min_ms=580_000,max_ms=700_000)
                    if e: ev.append(e)
        else:
            note=a.get('decision_note','')
        a2={'seat':seat,'name':a['name'],'physical_role':a['physical_role'],'decision':decision,
            'claimed_role':claimed,'claim_day':claim_day,'first_day_claim':first,'confidence':conf,
            'evidence':ev,'review_questions':[],'decision_note':note}
    # enforce current normalized identity (parts used dossier role already)
    old[(bv,seat)]=(g,a2)

# Add omission: 122 #2 has a possible ASR-isolated "我自己预言家" phrase, but the complete context is contradictory.
bv='BV1pSuN62Ekr'; _,p,d=by_bv[bv]; actual=next(s for s in d['seats'] if s['seat']==2)
evidence=[]
for phrase,inter in [('过了2号玩家请发言','法官明确交给2号首日发言。'),('我自己预言家','转写孤句似乎包含第一人称自称，但需要结合前后句判断，不能单独作为可靠跳身份证据。'),('我是比较想认为6号','2号随后明确表示自己更倾向相信6号，显示其当时在比较其他预言家并站边，而非显然建立自己的预言家身份。')]:
 e=find_ev(bv,phrase,'speech',inter,min_ms=1_450_000,max_ms=1_550_000)
 if e: evidence.append(e)
old[(bv,2)]=(None,{'seat':2,'name':actual['name'],'physical_role':actual['role'],'decision':'uncertain','claimed_role':'预言家','claim_day':1,'first_day_claim':None,'confidence':'low','evidence':evidence,'review_questions':['首日#2本人轮次1,490,000–1,545,000ms：孤句“我自己预言家”与前后持续比较6/10两位预言家、并说“我是比较想认为6号”的站边语境不一致；视频确认是2号本人发言但未显示其建立验人/警徽流，请回听核对该孤句是否ASR识别错误或实际起跳。'],'decision_note':'视频确认是2号本人在首日发言，但转写孤句“我自己预言家”与紧邻上下文比较6号/10号、倾向站边6号不符，画面也未显示2号有自己的验人或警徽流信息；不能断言为悍跳，保留具体语句待回听确认。'})

# Build game sections, only include candidates and a review row for the possible plan-only #8.
by_game=OrderedDict()
for (bv,seat),(_,a) in old.items():
    if bv not in by_bv: continue
    index,p,d=by_bv[bv]
    slug=d['slug']; gd=p.parent.relative_to(ROOT).as_posix()
    key=(index,bv)
    if key not in by_game:
        by_game[key]={'game_id':slug,'bvid':bv,'first_day_end_ms':day_end(bv,p,d),'assessments':[]}
    by_game[key]['assessments'].append(a)

# Stable order by sorted dossier index and seat.
games=[]
for (index,bv),g in sorted(by_game.items()):
    g['assessments'].sort(key=lambda x:x['seat'])
    games.append(g)

payload={'schema_version':1,'scope':'first_day','games':games}
for game in games:
    if game['bvid']=='BV1pSuN62Ekr':
        for assessment in game['assessments']:
            if assessment['seat']==2:
                assessment['visual_checks']=[{'path':'data/extractions/S22/bluff_review/video_recheck/BV1pSuN62Ekr_01519.000.png','time_ms':1519000,'observation':'画面确认当前发言者为2号蹄蹄；警徽流/验人信息在屏幕上属于4、6、10号，没有显示2号建立自身验人或警徽流。该画面不能单独判定孤句是否ASR错误。'}]
tmp=WORK/'recheck_c.json.tmp'
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
tmp.replace(WORK/'recheck_c.json')
print('wrote',len(games),'games',sum(len(x['assessments']) for x in games),'assessments', 'range',min(by_bv[g['bvid']][0] for g in games),max(by_bv[g['bvid']][0] for g in games))
