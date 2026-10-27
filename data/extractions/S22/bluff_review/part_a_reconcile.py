import json,pathlib
p=pathlib.Path('data/extractions/S22/bluff_review/part_a.json')
data=json.loads(p.read_text(encoding='utf-8-sig'))
# Resolved wolf bottom-card seats after cross-checking recap and first-day turns.
no_sets={
 2:[2,7,9], 3:[1,3,6], 12:[1,6,12], 13:[2,3,8], 14:[1,12], 15:[2,3,7], 16:[5,10],
 17:[8], 18:[1,8,10], 19:[2,4,6], 20:[2,7,8],
 21:[1,5,6], 22:[9,10,12], 23:[1,3,5], 24:[1,4,11],
 25:[5,8,10], 26:[1,9], 27:[1,4,5,6], 28:[3,8,9,12],
 29:[5,8,10], 30:[6,9], 31:[2,9,11], 32:[1,3,7], 33:[1,5,9],
 34:[2,6,11], 35:[1,3,5], 36:[3,4,5,8], 37:[1,7,8],
 38:[2,4,10], 39:[4,6], 40:[3,4,7], 41:[4,10],
 42:[1,4,9], 44:[5,9], 45:[1,8,10], 46:[3,6,8], 47:[1,7,8,10], 48:[4,5], 49:[3,10], 50:[2,5]
}
yes_overrides={
 12:{2:'预言家'},14:{10:'通灵师'},17:{10:'通灵师'},21:{12:'通灵师'},
 24:{7:'通灵师'},26:{3:'预言家',12:'预言家'},32:{2:'预言家'},
 19:{7:'预言家'},29:{11:'预言家'},30:{11:'预言家'},41:{12:'预言家'},44:{7:'预言家'},46:{12:'预言家'},48:{6:'通灵师',7:'预言家'},
 49:{12:'预言家'},50:{10:'预言家'}
}
# File source for exact localized transcript quotes.
root=pathlib.Path('.')
def source_for(game):
  dossier=root/game['game_dir']/'dossier.json'
  d=json.loads(dossier.read_text(encoding='utf-8-sig'))
  f=next((x for x in d.get('files',[]) if x.get('role')=='subtitle'),None)
  if not f: f=next((x for x in d.get('files',[]) if x.get('role')=='transcript'),None)
  return d,f

def seg_for(file,start):
  if not file: return None
  j=json.loads((root/file['path']).read_text(encoding='utf-8-sig'))
  if 'body' in j:
    raw=j['body']
    for x in raw:
      a=round(float(x.get('from',0))*1000)
      if a==start: return {'start_ms':a,'end_ms':round(float(x.get('to',x.get('from',0)))*1000),'text':x.get('content','')}
  else:
    for x in j.get('segments',[]):
      if int(x.get('start_ms',-1))==start: return {'start_ms':int(x['start_ms']),'end_ms':int(x.get('end_ms',x['start_ms'])),'text':x.get('text','')}
  return None

claims={
  (12,2):[(1638780,'speech','这段发言由2号作出，明确自称预言家。')],
  (14,10):[(777410,'speech','10号先称自己是通灵师，紧接着报验5号金水，属于完整信息神身份声明。')],
  (17,10):[(2298900,'commentary','6号发言明确称10号是悍跳狼，属于对特定座位的直接指认。')],
  (21,12):[(1106870,'speech','12号称自己拿通灵师，并接着给出警徽流，构成通灵师身份声明。')],
  (24,7):[(970620,'speech','7号在自己发言中称自己是通灵师并说明应当验人。')],
  (26,3):[(3369700,'speech','3号在自己发言中报8号查杀并明确自称预言家。')],
  (26,12):[(1812510,'speech','12号报验人结果并在后续同一发言明确自称预言家。'),(1896220,'speech','12号在同一发言中明确说“我是预言家牌”。')],
  (32,2):[(1177460,'speech','2号在自己的发言中报验8号金水，属于预言家身份声明。')],
  (41,12):[(1371520,'speech','12号自称预言家；该条字幕尾字疑似ASR错字，后续紧接验人结果和警徽流。'),(1373000,'speech','12号继续报出第一天验3号金水。'),(1375620,'speech','12号继续说明警徽流，和前一句连成预言家完整发言。')],
  (44,7):[(2007830,'speech','7号在自己的发言中直接自称预言家。')],
  (46,12):[(943960,'speech','12号在自己的首日发言中报验金水并描述自己的验人过程，属于预言家身份声明。')],
  (48,6):[(1784110,'speech','6号在自己的发言中直接自称通灵师，并指出10号起跳。')],
  (48,7):[(1101160,'speech','7号报验2号查杀，是预言家身份声明。')],
  (49,9):[(918960,'speech','9号明确自称通灵师牌，随后报首验结果。')],
  (49,12):[(1637780,'speech','12号在自己的发言中报验11号查杀，属于预言家身份声明。')],
  (50,10):[(1373300,'speech','10号在自己发言中明确自称预言家，之后继续报验人结果和金水。')],
  (50,8):[(1135829,'speech','8号在自己发言中称7号是自己验出的查杀，属于预言家身份声明。')]
}
# Helpful excerpts that explicitly identify a different seat as claimant; no decisions still explain full coverage.
other_claims={
  (13,2):(1440090,'该句是疑问“我是不是通灵师”，不是肯定的身份声明。'),
  (15,2):(1369160,'1369160附近的自称属于10号真预言家；12号另有复盘明确悍跳，未发现2号自称。'),
  (15,3):(1369160,'警上信息神自称由10号说出；3号后续只分析其他座位，复盘点名12号悍跳。'),
  (15,7):(1369160,'警上信息神自称由10号说出；7号未自称，复盘明确点名12号悍跳。'),
  (17,8):(2298900,'6号明确指认10号悍跳；8号未自称信息神。'),
  (18,8):(2674720,'3号称12号是队友起跳；8号未有信息神自称。'),
  (18,10):(2674720,'3号明确把12号称作起跳者；10号未自称信息神。'),
  (22,9):(642119,'6号、7号分别自称通灵师；9号未见该座位自称。'),
  (22,10):(642119,'6号、7号分别自称通灵师；10号未见该座位自称。'),
  (22,12):(642119,'6号、7号分别自称通灵师；12号未见该座位自称。'),
  (24,1):(970620,'明确自称发生在7号发言；1号未见信息神自称。'),
  (24,4):(970620,'明确自称发生在7号发言；4号未见信息神自称。'),
  (25,5):(495070,'首日可定位的预言家自称发生在6号，非5号。'),
  (25,8):(495070,'首日可定位的预言家自称发生在6号，非8号。'),
  (25,10):(495070,'首日可定位的预言家自称发生在6号，非10号。'),
  (26,1):(1896220,'12号有明确自称，3号另有明确自称；未发现1号自称。'),
  (26,9):(1896220,'12号、3号分别自称预言家；未发现9号自称。'),
  (28,3):(515000,'候选自称发生在2号发言，非3号。'),
  (28,8):(515000,'候选自称发生在2号发言，非8号。'),
  (28,9):(515000,'候选自称发生在2号发言，非9号。'),
  (28,12):(515000,'候选自称发生在2号发言，非12号。'),
  (29,5):(2143829,'直接预言家自称及报查杀属于11号；5号未见自称。'),
  (29,8):(2143829,'直接预言家自称及报查杀属于11号；8号未见自称。'),
  (29,10):(2143829,'直接预言家自称及报查杀属于11号；10号未见自称。'),
  (31,11):(3263550,'11号说的是“警下我会跳通灵师”，随后谈狼队骗信息神的计划；这是未来意图，不是本局已作出的身份声明。'),
  (32,1):(1177460,'自称与验人结果属于2号发言，非1号。'),
  (32,3):(1177460,'自称与验人结果属于2号发言，非3号。'),
  (32,7):(1177460,'自称与验人结果属于2号发言，非7号。'),
  (33,1):(1668750,'8号发言明确指认6号悍跳；1号未自称信息神。'),
  (33,9):(1668750,'8号发言明确指认6号悍跳；9号未自称信息神。'),
  (34,2):(1549090,'明确信息神自称属于12号；2号未见自称。'),
  (34,6):(1549090,'明确信息神自称属于12号；6号未见自称。'),
  (34,11):(1549090,'明确信息神自称属于12号；11号未见自称。'),
  (35,1):(1739720,'2号说明自己是悍跳狼；1号未有自称。'),
  (35,3):(1739720,'3号发言只讨论6号是否预言家；未自称。'),
  (35,5):(1739720,'5号发言只讨论其他人是否预言家；未自称。'),
  (36,3):(2037120,'2号盗宝大师候选没有成真；可定位的预言家自称由9号说出，3号仅使用条件句。'),
  (36,4):(2037120,'可定位的预言家自称由9号说出；4号未自称信息神。'),
  (36,5):(2037120,'可定位的预言家自称由9号说出；5号未自称信息神。'),
  (36,8):(2037120,'可定位的预言家自称由9号说出；8号未自称信息神。'),
  (38,2):(2248900,'12号、11号有信息神自称；2号未见信息神自称。'),
  (38,4):(2248900,'12号、11号有信息神自称；4号未见信息神自称。'),
  (38,10):(2248900,'12号、11号有信息神自称；10号未见信息神自称。'),
  (40,3):(1242090,'通灵师自称属于10号，8号明确把10号说成悍跳；3号未见自称。'),
  (40,4):(1242090,'通灵师自称属于10号，8号明确把10号说成悍跳；4号未见自称。'),
  (40,7):(1242090,'通灵师自称属于10号，8号明确把10号说成悍跳；7号未见自称。'),
  (41,4):(1371520,'带验人和警徽流的预言家自称属于12号；4号未自称。'),
  (41,10):(1371520,'带验人和警徽流的预言家自称属于12号；10号未自称。'),
  (42,1):(872460,'预言家自称属于2号；1号未见信息神自称。'),
  (42,4):(872460,'预言家自称属于2号；4号未见信息神自称。'),
  (42,9):(872460,'预言家自称属于2号；9号未见信息神自称。'),
  (44,5):(2007830,'7号直接自称预言家，且旁白明确12号悍跳；5号未自称。'),
  (44,9):(2007830,'7号直接自称预言家，且旁白明确12号悍跳；9号未自称。'),
  (45,8):(1902560,'可定位的预言家自称属于6号；8号只讨论预言家。'),
  (45,10):(1902560,'可定位的预言家自称属于6号；10号未见自称。'),
  (46,3):(943960,'第一天明确的预言家自称和验人结果属于12号；3号没有自称。'),
  (46,6):(943960,'第一天明确的预言家自称和验人结果属于12号；6号没有自称。'),
  (46,8):(943960,'第一天明确的预言家自称和验人结果属于12号；8号没有自称。'),
  (47,1):(514120,'首轮从6号开始；6号报2号查杀并自称预言家，另一处候选自称归于2号发言；未发现1号自称。'),
  (47,7):(514120,'首轮从6号开始；6号报2号查杀并自称预言家，另一处候选自称归于2号发言；未发现7号自称。'),
  (47,8):(514120,'首轮从6号开始；6号报2号查杀并自称预言家，另一处候选自称归于2号发言；未发现8号自称。'),
  (47,10):(514120,'首轮从6号开始；6号报2号查杀并自称预言家，另一处候选自称归于2号发言；未发现10号自称。'),
  (48,4):(1784110,'6号直接自称通灵师；4号未见信息神自称。'),
  (48,5):(1784110,'6号直接自称通灵师；5号未见信息神自称。'),
  (49,3):(918960,'9号、11号有通灵师自称；3号仅明确指认9号悍跳，未见其自称。'),
  (49,10):(918960,'9号、11号有通灵师自称；10号表达想当通灵师而非身份声明。'),
  (50,2):(1373300,'10号明确自称预言家，8号也报验人；2号未见自称。'),
  (50,5):(1373300,'10号明确自称预言家，8号也报验人；5号未见自称.')
}
# Existing yes candidates supported by recap remain yes; use exact confirmed source excerpts where available.
for gi,game in enumerate(data['games'],1):
  dossier,sub=source_for(game)
  if gi in (5,37,43): game['coverage']='recap_and_claims'
  for a in game.get('assessments',[]):
    seat=a['seat']; key=(gi,seat)
    if seat in yes_overrides.get(gi,{}):
      role=yes_overrides[gi][seat]
      a['decision']='yes'; a['claimed_role']=role; a['confidence']='high'; a['review_questions']=[]
      excerpts=[]
      for start,kind,interp in claims.get(key,[]):
        seg=seg_for(sub,start)
        if seg and seg['text']:
          excerpts.append({'kind':kind,'source_path':sub['path'],'start_ms':seg['start_ms'],'end_ms':seg['end_ms'],'text':seg['text'],'interpretation':interp})
      # Keep recap evidence and remove duplicate entries, then append exact direct speech evidence.
      ev=[]
      for e in a.get('evidence',[]):
        if e not in ev: ev.append(e)
      for e in excerpts:
        if e not in ev: ev.append(e)
      a['evidence']=ev
      a['decision_note']='确认狼人底牌在首日以信息神身份发言；按本项目口径计为悍跳。'
      continue
    if seat in no_sets.get(gi,[]):
      a['decision']='no'; a['claimed_role']=None; a['confidence']='medium'; a['review_questions']=[]
      detail='首日警上发言及复盘原文中未发现该座位自称预言家或通灵师，亦无复盘明确点名该座位悍跳。'
      if key in other_claims:
        start,why=other_claims[key]; detail=why
        seg=seg_for(sub,start)
        if seg and seg['text']:
          a['evidence']=[{'kind':'speech' if sub and sub.get('role') in ('subtitle','transcript') else 'recap','source_path':sub['path'],'start_ms':seg['start_ms'],'end_ms':seg['end_ms'],'text':seg['text'],'interpretation':why}]
      else:
        a['evidence']=[]
      a['decision_note']='已检查复盘原文与首日警上发言/悍跳、验人、警徽流相关全文转写；'+detail
      continue
    if key==(17,5):
      a['decision']='uncertain'; a['confidence']='low'; a['claimed_role']='通灵师'
      a['review_questions']=['请复核5号的“我要通灵师”是在表达愿望/玩笑，还是在以通灵师身份起跳。']
      if a.get('evidence'):
        a['evidence'][0]['interpretation']='5号被发言边界定位到含“要不然你比我更适合做通灵师呀”及“我要通灵师”的一轮；前者像在谈角色适配，后者的身份语义不够清楚。'
for game in data['games']:
  for a in game.get('assessments',[]):
    # Calls intentionally left empty per parent’s latest instruction.
    if a.get('calls') is None: a['calls']=[]
    if a.get('decision')=='no' and not a.get('decision_note'):
      a['decision_note']='已检查复盘原文与首日警上发言/悍跳、验人、警徽流相关全文转写；未发现该座位自称预言家或通灵师，也无复盘明确点名该座位悍跳。'
# Exact source text corrections from preflight.
for a in data['games'][0]['assessments']:
  if a['seat']==12:
    for e in a.get('evidence',[]):
      if e.get('start_ms')==3213310: e['text']='我觉得2号五号'
for a in data['games'][15]['assessments']:
  for e in a.get('evidence',[]):
    if e.get('start_ms')==3803540: e['text']='6号悍跳狼获得警徽'
# Shorten evidence to exact source segments; earlier drafts joined separated ASR segments.
for a in data['games'][1]['assessments']:
  if a['seat']==5:
    for e in a.get('evidence',[]):
      if e.get('start_ms')==1279240:
        e['start_ms']=1291440; e['end_ms']=1293000; e['text']='我验的6号玩家是金水嗯'
for a in data['games'][2]['assessments']:
  if a['seat']==5:
    for e in a.get('evidence',[]):
      if e.get('start_ms')==794240: e['end_ms']=795370; e['text']='我这个通灵师'
for a in data['games'][3]['assessments']:
  if a['seat'] in (6,7):
    for e in a.get('evidence',[]):
      if e.get('start_ms')==2727615: e['end_ms']=2728735; e['text']='七在警上悍跳完以后，'
for a in data['games'][4]['assessments']:
  if a['physical_role'] in ('狼人','假面'):
    # Find the full transcript from the game dossier because this board lacks a platform subtitle role.
    dossier=json.loads((root/data['games'][4]['game_dir']/'dossier.json').read_text(encoding='utf-8-sig'))
    tf=next((f for f in dossier.get('files',[]) if f.get('role')=='transcript'),None)
    if tf:
      a['evidence']=[{'kind':'speech','source_path':tf['path'],'start_ms':224500,'end_ms':225500,'text':'我身为一个狼人我来悍跳一张预言家牌，','interpretation':'此句出现在首轮法官点座位发言之前，speaker未标注，可能是战术解说或角色讨论，不能映射到具体狼座位。'}]
      a['review_questions']=['请复核224500处是本局玩家实际发言还是前置解说；若属实际发言，请确认发言座位。']
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('updated',len(data['games']),'games')
