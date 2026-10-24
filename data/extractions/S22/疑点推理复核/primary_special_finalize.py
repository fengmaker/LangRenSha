from pathlib import Path
import sys,copy
sys.path.insert(0,'scripts')
import batch_s22 as b
from s22_inference_review import BASE,evidence_check
p=b.read_json(BASE/'special_plan.json'); state=b.load_state(); games={g['bvid']:g for g in p['games']}
def change(k,n,ph,slot,**fields):
 g=games[k]
 old=next((c for c in g['changes'] if c['kind']=='event' and c['number']==n and c['phase']==ph and c['slot']==slot),None)
 if old:old['fields'].update(fields)
 else:g['changes'].append(dict(kind='event',number=n,phase=ph,slot=slot,fields=fields))
def decision(k,id,conclusion,reason):
 g=games[k];d=next((d for d in g['decisions'] if d['id']==id),None)
 if d:d.update(conclusion=conclusion,reason=reason)
 else:g['decisions'].append(dict(id=id,resolved=True,conclusion=conclusion,reason=reason,basis='source_context_and_rules',confidence='high',evidence=[]))
k='BV1PEN863EXG'
change(k,1,'day','self_destruct',action='none',actor=None,targets=[],result='9号狼王自爆发生于第二天；首日无自爆')
change(k,2,'day','self_destruct',action='self_destruct',actor=9,targets=[],result='第二天白天9号狼王自爆')
change(k,3,'night','treasure_extra_attack',action='unavailable',actor=1,targets=[],result='余牌无蒙面人牌；原刀4号属于第四夜普通狼刀，非本夜额外刀')
k='BV1h33z6tEqx'
games[k]['changes'].append(dict(kind='seat',seat=12,fields=dict(faction='werewolf')))
change(k,3,'night','dreamer_action',action='dream',actor=4,targets=[12],result='首次梦游12号；摄梦人4号被刀后带走当夜梦游对象12号')
change(k,3,'night','treasure_extra_attack',action='unavailable',actor=12,targets=[],result='余牌无蒙面人，未触发额外刀；最后狼人接普通狼刀')
change(k,3,'night','wolf_attack',action='attack',actor=12,targets=[4],result='狼阵营盗宝大师12号接普通狼刀击杀4号摄梦人')
change(k,3,'day','night_deaths',action='die',targets=[4,12],result='狼刀4号摄梦人；其死亡带走当夜梦游对象12号盗宝大师')
change(k,2,'day','badge',actor=1)
decision(k,'00b773bde46933','R3摄梦人4号首次梦游12号盗宝大师；4号被普通狼刀击杀后，带走当夜梦游对象12号。','R1/R2连续梦游的是6号，R3才转梦12号。原文明确盗宝大师刀4、摄梦人梦12及双死；死亡机制为摄梦人出局连带，不是连续梦死。')
decision(k,'6d714611bb349d','R3夜死为4、12号：盗宝大师12号接普通狼刀杀4，摄梦人4号出局连带12；不是4、2，也不是额外技能刀。','“42”结合刀4、梦12、好人获胜可唯一还原为4/12。盗宝大师明示狼人阵营，余牌仅平民、毒师及狼人，不含蒙面人，故不具备蒙面额外刀。')
k='BV1hFM26ME7o'
change(k,2,'day','night_deaths',action='die',targets=[3,10,12],result='狼刀3号摄梦人；摄梦人死亡带走当夜梦游对象10号；毒师毒杀12号')
decision(k,'322ec14a05fd15','R2夜死为3、10、12：狼刀3号摄梦人，其死亡带走当夜梦游对象10号盗宝大师；毒师毒杀12号狼王。','R1摄梦对象为5号，R2才梦10号，因此不是连续梦游。狼刀3与梦10构成连带双死，毒12再增一名死者；随后末狼1号自爆、好人获胜与三死吻合。')
k='BV1Nsgy6cEiG'
change(k,2,'day','night_deaths',action='die',targets=[2,3,6],result='狼刀3号摄梦人；其死亡带走当夜梦游对象2号；毒师毒杀6号狼王')
decision(k,'99b172b3b9bf5f','R2夜死为2、3、6：狼刀3号摄梦人，其死亡连带当夜梦游对象2号盗宝大师；毒师毒杀6号狼王。','R1梦5，R2才梦2，故不是连续梦死。原文明报2/3双死，随后毒6并以损坏数字串总结；无防毒机制，毒6成立。第一天放逐的是9号平民；第二天狼队交牌，好人获胜。')
k='BV1gvTi66E7y'
for id in ['586a6926cb6428','b9883075adb64e']:
 decision(k,id,'R4诡术师4号交换自己与8号女巫；魔术师7号另交换2号平民和10号定序王子。','原文连读为“诡术师交换4号诡术师、8号女巫；魔术师交换2号平民、10号定序王子”。8号属于前一行动的第二目标，魔术师行动者仍是7号。')
k='BV1mDun6wEhp'
decision(k,'a28614b1a5b81f','R1诡术师10号交换9号狼人和12号女巫；5、11号为平民名单尾。','身份名单结束后，行动段明说交换9号狼人和12号女巫；诡术师的底牌座位为10号，9号是交换目标。')
k='BV1vH7R6tEQp'
decision(k,'a26381703a4ba4','R2舞池少数方7号假面共舞出局，夜死名单另合并狼刀8号，得到7/8双死。','共舞结算槽应以7号为单一死亡目标；夜死名单汇总不同来源的死者。旧校验器错误要求该槽零目标，已修正为单一目标。')
k='BV1aXgW6nE6E'
decision(k,'4e59ae0bd81b72','3号蒙面人在R4白天发言后延迟死亡；复盘中的“第二天”属于轮次口误或转写误差。','第三天放逐1号后才入夜刀3号，按统一轮次为R4夜；蒙面人依规则延迟至紧接的R4白天发言后死亡，不能提前写入R2或R3。')
k='BV1tj8p6RE2h'
for d in games[k]['decisions']:
 if d['id']=='60eb3400a524e5':d['reason']='舞池3号狼人、11/12号平民是1狼2好；面具给池外10号，不改变池内阵营，故少数狼阵营3号被共舞出局。'
 if d['id']=='e228c16f044384':d['reason']='舞池4号平民、5号白神、10号假面；面具使5号在当夜舞池按狼人阵营计算，4号成为少数方。舞者6号在池外，不能享受舞池狼刀保护，故另被刀出局。'
k='BV1xYEo6QE3E'
change(k,2,'night','dancer_dance',action='dance',actor=12,targets=[8,9,12],result='原文跨行明确8号预言家、9号平民、12号舞者；三好人无共舞死亡')
change(k,3,'night','masquerade_verify',action='verify',actor=4,targets=[12],result='不在舞池')
decision(k,'additional:dance_pool:2','R2舞池为8、9、12；原来的9、4、8把12号误成4号，导致4号被重复共舞。','两行连续原文直接列8号预言家、9号平民、12号舞者；随后明确舞池无事。R3才是3/4/7，三轮成员互不重复，符合每人仅共舞一次。')
k='BV1KMur6HE7b'
for slot in ['masquerade_verify','masquerade_mask']:
 change(k,1,'night',slot,action='unknown',actor=1,targets=[],result=None)
change(k,2,'night','masquerade_verify',action='verify',actor=1,targets=[9],result='不在舞池')
change(k,3,'night','dance_resolution',action='minority_dies',targets=[7],result='舞池7/10/11中少数狼阵营7号共舞出局')
decision(k,'additional:mask_phase','9号验证、8号面具均属于R2；R1未叙述这两项行动，撤回误复制到R1的事件。','原文先报首夜刀毒、警上2号自爆，之后入夜列舞池1/4/12，才报验9不在池及给8面具；把同一段同时写进R1/R2会造成连续重复目标。')
# Match the formal transcript verbatim, keeping rule and independent audio evidence separately.
cache={}
for g in p['games']:
 e=state['items'][g['bvid']];v=b.read_json(b.ROOT/e['output_dir']/'dossier.json');r=b.read_json(b.ROOT/e['output_dir']/'复核记录.json')
 segs=r.get('recap_segments',[])
 assert segs,g['bvid']
 evidence=dict(path=e['source_path'],start_ms=min(s['start_ms'] for s in segs),end_ms=max(s['end_ms'] for s in segs),quote=' '.join(s['text'] for s in segs))
 assert evidence_check(evidence,cache)['literal_match'],g['bvid']
 if v['board']=='treasure_master':
  current=next(x for x in v['rounds'][0]['night'] if x['slot']=='wolf_attack')
  if current['action']!='forbidden':
   change(g['bvid'],1,'night','wolf_attack',action='forbidden',actor=None,targets=[],result='盗宝大师版型首夜规则禁刀')
  rule=next(line for line in Path('docs/10_版型规则与夜间顺序.md').read_text(encoding='utf-8').splitlines() if line.startswith('余牌中只要有狼人阵营角色'))
 else:rule=None
 for d in g['decisions']:
  keep=[ev for ev in d.get('evidence',[]) if (ev['path'].startswith('docs/') or ev['path'].startswith('outputs/')) and evidence_check(ev,cache)['literal_match']]
  d['evidence']=[copy.deepcopy(evidence)]+keep
  if rule:d['evidence'].append(dict(path='docs/10_版型规则与夜间顺序.md',quote=rule))
  if g['bvid']=='BV119TJ6pEtC' and d['id']=='2e8c4815a248be':
   pool=next(line for line in Path('docs/10_版型规则与夜间顺序.md').read_text(encoding='utf-8').splitlines() if line.startswith('这是**候选牌堆'))
   d['evidence'].append(dict(path='docs/10_版型规则与夜间顺序.md',quote=pool))
 g['summary']='；'.join(dict.fromkeys(d['conclusion'] for d in g['decisions']))
b.atomic_json(BASE/'special_plan.json',p)
print('Finalized',len(p['games']),'games')
