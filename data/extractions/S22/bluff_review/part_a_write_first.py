import json,pathlib
root=pathlib.Path('.')
games=sorted((root/'data/games/S22').glob('*/dossier.json'),key=lambda p:str(p))

def evidence(kind,path,start,end,text,interpretation):
 return {'kind':kind,'source_path':path,'start_ms':start,'end_ms':end,'text':text,'interpretation':interpretation}
entries=[]
# game 1
p=games[0]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); sub=next(x['path'] for x in d['files'] if x['role']=='subtitle'); recap=f'{gd}/复盘原文.txt'
entries.append({'game_id':d['slug'],'bvid':'BV1kGVC6cEyg','date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':['检查了复盘原文与警上、首日候选词全文；未以候选资格或警徽结果单独推定跳身份。'],'assessments':[
 {'seat':1,'name':'二妖','physical_role':'狼人','decision':'uncertain','claimed_role':None,'confidence':'low','evidence':[evidence('recap',recap,5026460,5028300,'8号悍跳狼人获得警徽','复盘确认8号悍跳，但未确认1号发言；1号是否有自称仍需回听首日完整发言。')],'calls':[],'review_questions':['请复核1号警上/首日完整发言是否存在自称预言家或通灵师。']},
 {'seat':3,'name':'狼行','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('speech',sub,1273060,1275500,'我入夜之前跳预言家的概率','位于3号警上发言；这里谈的是跳预言家的概率，不是自称。已核对其余警上文字，未见自称预言家或通灵师。')],'calls':[],'review_questions':[]},
 {'seat':8,'name':'牛肉干','physical_role':'狼人','decision':'yes','claimed_role':'预言家','confidence':'high','evidence':[evidence('recap',recap,5026460,5028300,'8号悍跳狼人获得警徽','法官复盘明确点名8号悍跳，dossier底牌为狼人；同一段也记载其获得警徽。')],'calls':[],'review_questions':[]},
 {'seat':12,'name':'李舒服','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('speech',sub,3213310,3216090,'听完警下的发言，我觉得2号5号','位于12号首日发言开头；该段讨论他人身份，并结合全文核查未见其自称信息神。')],'calls':[],'review_questions':[]}
]})
# game 2
p=games[1]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); sub=next(x['path'] for x in d['files'] if x['role']=='subtitle'); recap=f'{gd}/复盘原文.txt'
entries.append({'game_id':d['slug'],'bvid':'BV1CGVC6cE8T','date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':['复盘确认10号通灵师获得警徽、首日4号平民被抗推；另检查首日候选与信息神自称全文。'],'assessments':[
 {'seat':2,'name':'Dreamyu','physical_role':'狼人','decision':'uncertain','claimed_role':None,'confidence':'low','evidence':[evidence('recap',recap,7422469,7427489,'10号通灵师获得警徽；第一天白天4号平民被抗推出局','复盘未点名2号悍跳，完整首日文本中未能将其他提及可靠归为2号；待复核。')],'calls':[],'review_questions':['请复核2号首日发言的完整语音归属。']},
 {'seat':5,'name':'耿许儿','physical_role':'盗宝大师','decision':'yes','claimed_role':'通灵师','confidence':'high','evidence':[evidence('speech',sub,1279240,1294410,'我警徽流留一个3号玩家，然后留个12号玩家，我验的6号玩家是金水','该片段紧接“过了5号玩家请发言”，且5号发言提出警徽流与验人结果，构成通灵师自称/报验；底牌为狼人阵营盗宝大师。')],'calls':[],'review_questions':[]},
 {'seat':7,'name':'JY','physical_role':'狼王','decision':'uncertain','claimed_role':None,'confidence':'low','evidence':[evidence('recap',recap,7422469,7427489,'10号通灵师获得警徽；第一天白天4号平民被抗推出局','复盘没有点名7号悍跳；已检查首日全文但无法确认是否有未识别的7号自称。')],'calls':[],'review_questions':['请复核7号警上及首日发言是否有信息神自称。']},
 {'seat':9,'name':'郭小炜','physical_role':'狼人','decision':'uncertain','claimed_role':None,'confidence':'low','evidence':[evidence('recap',recap,7422469,7427489,'10号通灵师获得警徽；第一天白天4号平民被抗推出局','复盘没有点名9号悍跳；转写中的首日发言归属不足以排除或确认9号自称。')],'calls':[],'review_questions':['请复核9号警上及首日发言。']}
]})
# game 3
p=games[2]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); sub=next(x['path'] for x in d['files'] if x['role']=='subtitle'); recap=f'{gd}/复盘原文.txt'
entries.append({'game_id':d['slug'],'bvid':'BV1pGVC6cEbW','date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':['复盘称5号悍跳后自爆；全文中5号警上发言含通灵师自称表达。'],'assessments':[
 {'seat':1,'name':'二妖','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('speech',sub,380960,477930,'一号玩家呢第一个发言……我是一个好人','首日明确提示1号发言；核查该发言全文未见其自称预言家或通灵师。')],'calls':[],'review_questions':[]},
 {'seat':3,'name':'狼行','physical_role':'狼人','decision':'uncertain','claimed_role':None,'confidence':'low','evidence':[evidence('recap',recap,4472739,4474230,'5号悍跳狼人自爆','复盘明确点名5号；首日转写对3号发言归属不完整，尚不能排除其他自称。')],'calls':[],'review_questions':['请复核3号上警/警下首日完整发言。']},
 {'seat':5,'name':'耿许儿','physical_role':'狼人','decision':'yes','claimed_role':'通灵师','confidence':'high','evidence':[evidence('recap',recap,4472739,4474230,'5号悍跳狼人自爆','复盘明确点名5号悍跳且底牌匹配。'),evidence('speech',sub,794240,800900,'我这个通灵师……不要因为这个点不投给我','5号玩家发言段出现通灵师身份主张，并请求投票支持。')],'calls':[],'review_questions':[]},
 {'seat':6,'name':'李斯','physical_role':'机械狼','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('speech',sub,923610,939730,'我觉得5号玩家发言呢其实没有什么问题……搏杀到了他通灵师','6号发言讨论5号和通灵师，没有把自己称为通灵师/预言家；核查该段及其首日发言未见自称。')],'calls':[],'review_questions':[]}
]})
# game 4
p=games[3]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); bvid='BV1hb7R6XEtD'; source=next(x.as_posix() for x in (root/'data/seasons/S22').glob(f'**/*{bvid}*.本地全文转写_funasr.json')); recap=f'{gd}/复盘原文.txt'
entries.append({'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'recap_and_claims','notes':['首日全文转写提到7号在警上悍跳。2号物理身份为混血儿而非狼人底牌；全文转写另有“我汤米维维是预言家”自称，按规则单独待复核，不作狼人悍跳计数。'],'assessments':[
 {'seat':5,'name':'耿许儿','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('recap',recap,5030555,5034235,'十一号预言家女巫通过冤将验证十二号两位好人身份','警上到首日全文检查中未找到5号自称预言家或通灵师；该段提供当日信息神身份作核对。')],'calls':[],'review_questions':[]},
 {'seat':6,'name':'KS','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('commentary',source,2727615,2728735,'七在警上悍跳完以后，六已经是一个倒钩狼','分析明确说7号悍跳、6号倒钩；未把6号误归为悍跳者。')],'calls':[],'review_questions':[]},
 {'seat':7,'name':'小苍','physical_role':'狼人','decision':'yes','claimed_role':'预言家','confidence':'medium','evidence':[evidence('commentary',source,2727615,2728735,'七在警上悍跳完以后，六已经是一个倒钩狼','评论明确归因7号在警上悍跳；dossier座位7底牌为狼人。'),evidence('commentary',source,2774925,2776705,'正常来说七起起来悍跳','同一复盘语境再次点名7号悍跳。')],'calls':[],'review_questions':[]},
 {'seat':10,'name':'苏打','physical_role':'狼人','decision':'no','claimed_role':None,'confidence':'medium','evidence':[evidence('recap',recap,5041675,5043555,'十号狼人被公投出局','检查警上与首日全文未发现10号自称信息神；复盘只确认10号底牌与放逐结果，不以此判悍跳。')],'calls':[],'review_questions':[]}
]})
# game 5
p=games[4]; d=json.loads(p.read_text(encoding='utf-8-sig')); gd=p.parent.as_posix(); bvid='BV1vH7R6tEQp'; source=next(x.as_posix() for x in (root/'data/seasons/S22').glob(f'**/*{bvid}*.本地全文转写_funasr.json')); recap=f'{gd}/复盘原文.txt'
unknown_ev=evidence('speech',source,650855,660015,'对吧我这把是预言家……我自己是预言家牌','全文转写出现玩家第一人称信息神自称，但speaker为unassigned，无法和座位对应；不得仅凭底牌候选推定。')
entries.append({'game_id':d['slug'],'bvid':bvid,'date':d['date'],'game_number':d['game_number'],'game_dir':gd,'coverage':'partial','notes':['检查复盘与本地FunASR全文转写；转写speaker均未标注，片段“我这把是预言家/我自己是预言家牌”无法对应座位。平台AI字幕另行查看，但无法解决该语音归属。'],'assessments':[
 {'seat':5,'name':'耿许儿','physical_role':'狼人','decision':'uncertain','claimed_role':'预言家','confidence':'low','evidence':[unknown_ev],'calls':[],'review_questions':['该信息神自称能否对应5号？请复核原视频发言轮次。']},
 {'seat':7,'name':'小苍','physical_role':'假面','decision':'uncertain','claimed_role':'预言家','confidence':'low','evidence':[unknown_ev],'calls':[],'review_questions':['该信息神自称能否对应7号？请复核原视频发言轮次。']},
 {'seat':10,'name':'苏打','physical_role':'狼人','decision':'uncertain','claimed_role':'预言家','confidence':'low','evidence':[unknown_ev],'calls':[],'review_questions':['该信息神自称能否对应10号？请复核原视频发言轮次。']},
 {'seat':12,'name':'李舒服','physical_role':'狼人','decision':'uncertain','claimed_role':'预言家','confidence':'low','evidence':[unknown_ev],'calls':[],'review_questions':['该信息神自称能否对应12号？请复核原视频发言轮次。']}
]})
out={'schema_version':1,'range':[1,50],'games':entries}
outpath=root/'data/extractions/S22/bluff_review/part_a.json'
outpath.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(outpath.as_posix(),len(entries),sum(len(x['assessments']) for x in entries),sum(a['decision']=='yes' for x in entries for a in x['assessments']),sum(a['decision']=='uncertain' for x in entries for a in x['assessments']))
