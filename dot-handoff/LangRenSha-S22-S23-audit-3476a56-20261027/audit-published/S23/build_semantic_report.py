import pathlib,json,hashlib,csv,subprocess,collections,re
B=pathlib.Path('/workspace/scratch/a7edd912716e/audit-published/S23');E=B/'evidence';R=B.parent.parent/'langrensha-cloud';REF='3476a56af155f36a0d0050abc1660ed0d6fd538a'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
A=read(B/'per_game_audit.json');G={g['bvid']:g for g in A['games']};D={};F={};V={};S={}
for id,g in G.items():
 F[id]=next((E/'data/games/S23').glob('*'+id));D[id]=read(F[id]/'dossier.json');V[id]=read(F[id]/'voting.json');r=read(E/g['source']['path']);S[id]=[]
 for i,x in enumerate(r.get('segments',r.get('body',[]))):
  a=x.get('start_ms',round(x.get('from',x.get('start',0))*1000));b=x.get('end_ms',round(x.get('to',x.get('end',0))*1000));t=x.get('text',x.get('content',''));S[id].append({'row':i,'start_ms':a,'end_ms':b,'text':t})
def ev(id,n,ph,slot):return next(e for r in D[id]['rounds'] if r['number']==n for e in r[ph] if e['slot']==slot)
def anchor(id,a,b,label='归档原字幕/ASR，非本轮回听音频'):
 rows=[r for r in S[id] if r['end_ms']>a and r['start_ms']<b]
 return {'path':G[id]['source']['path'],'sha256':G[id]['source']['sha256'],'start_ms':a,'end_ms':b,'rows':rows,'quote':'\n'.join(r['text'] for r in rows),'level':'archived_transcript_direct_read','label':label}
def fileanchor(p,locator='',note=''):
 return {'path':str(p.relative_to(E)),'sha256':sha(p),'locator':locator,'note':note}
def change(id,n,ph,slot,candidate,subfield=None):
 old=ev(id,n,ph,slot);old=old.get(subfield) if subfield else old
 return {'field':f'rounds[{n}].{ph}.{slot}'+('.'+subfield if subfield else ''),'formal_path':str((F[id]/'dossier.json').relative_to(E)),'formal_sha256':sha(F[id]/'dossier.json'),'formal_current_value':old,'candidate_value':candidate,'applied':False}
findings=[]
def add(num,id,title,priority,changes,windows,reason,exclusions,confidence='high_archived_text',gaps=None,extras=None,kind='source_fact_conflict'):
 g=G[id];p=E/'data/extractions/S23/game_reviews'/id/'daily_audit.json';x={'id':f'S23-F{num:02d}','bvid':id,'game_id':g['game_id'],'date':g['date'],'game_number':g['game_number'],'title':title,'priority':priority,'kind':kind,'status':'candidate_only_not_applied','confidence':confidence,'changes':changes,'source_evidence':[anchor(id,*w) for w in windows],'prior_review':fileanchor(p,'/checks','完整保存最新旁证，与正式值双向对照；旁证不是新媒体核验'),'prior_review_checks':g['prior_audit_checks'],'reasoning':reason,'alternative_explanations_checked':exclusions,'remaining_gap':gaps or ['未回听原音；不把平台字幕绝对等同原话。','候选只保存供下一轮审批，不改正式数据。'],'extra_evidence':extras or []};findings.append(x);return x
p=F['BV1KaaT67Eca']/'dossier.json';seat=next(s for s in D['BV1KaaT67Eca']['seats'] if s['seat']==4)
add(1,'BV1KaaT67Eca','混血儿4号榜样12/好人阵营与8号狼人榜样复盘冲突','P1',[
 change('BV1KaaT67Eca',1,'night','mixed_blood_model',[8],'targets'),{'field':'seats[4].faction','formal_path':str(p.relative_to(E)),'formal_sha256':sha(p),'formal_current_value':seat['faction'],'candidate_value':'werewolf','applied':False}],[(4799000,4812000)],'最新daily检查已写4选8狼人，正式却仍选12预言家并记good。角色仍混血儿，物理狼数不改变；整局good胜不改变。',['不存在把12理解为学习对象的替代：事件slot明确mixed_blood_model，榜样8是复盘明说。','原保存图4真身份混血儿、8狼人、12预言家；黄字混8仅旁证自述，非单独定案。','网站未覆盖修正，独立mapping真实函数内存候选重算荣耀本局胜+1→负-1、S23总分3→1，详见../mapping/candidate-BV1KaaT67Eca-impact.json。'],confidence='high_text_plus_targeted_saved_frame',extras=[fileanchor(E/'data/extractions/S23/speech_frames/BV1KaaT67Eca/BV1KaaT67Eca_04723.380.png','t=4723380ms','本助手与root独立目视；非回听原音。'),{'path':'../mapping/candidate-BV1KaaT67Eca-impact.json','type':'conditional_not_a_correction'}])
add(2,'BV1g1YU6kERd','青丘前两昼死亡错位且漏5，末夜说明误把11称九尾','P1',[
 change('BV1g1YU6kERd',1,'day','night_deaths',{'action':'peaceful','targets':[]}),change('BV1g1YU6kERd',2,'day','night_deaths',{'action':'die','targets':[1,5]}),change('BV1g1YU6kERd',4,'day','night_deaths','N4狼刀11号守卫单死；删除本局无据的11号九尾毒免疫句。','result')],[(1786000,1791000),(2967000,2975000),(4001000,4006000),(4249000,4254000),(4452000,4505500),(4532000,4579000)],'法官现场播报和连续末复盘均为N1刀3被救平安，N2刀5毒1双死，N3刀8，N4刀11。正式D1[1]、D2[8]、D3[8]重复错误；实际九尾4、11守卫。',['开局夜=内部N1；D1狼9爆后入N2、D2狼7爆后入N3、D3狼10爆后入N4，完整连续链已核。','supplemental为空，primary无额外死亡补齐；首夜平安、次夜1/5双死均有对局中法官宣布，不能用延迟宣布解释。','D4原保存图确认1毒/5刀/8刀/11刀以及9/7/10爆；图本身不单独证明各夜时点。','九尾猎杀只在后段导致3/6出局，随后拍12；不得把这些提前加入夜死。config/S23_review_rules.json是本局法官阈值复盘交叉，并非另行目视官方规则图。','末复盘一次说“第三天”与连续自爆链和D4原图冲突，保留该口误，不拿它反推全部夜次。'],confidence='high_text_plus_targeted_saved_frame',extras=[fileanchor(E/'data/extractions/S23/speech_frames/BV1g1YU6kERd/BV1g1YU6kERd_04411.719.png','t=4411719ms','本轮直接目视D4死亡状态及底牌，不声称此帧证明所有夜次。'),fileanchor(E/'config/S23_review_rules.json','/rules/0','本局法官结算旁证；本轮未读取外部官方规则图。')])
add(3,'BV1theH6cESW','D2夜死漏9号毒口','P1',[change('BV1theH6cESW',2,'day','night_deaths',[6,9],'targets')],[(4534000,4539500),(6955000,6974500)],'正式已有N2刀6、毒9，法官宣布6/9倒牌及末复盘六九双死，但D2 targets只有6。',['首夜平安→D1放逐11→N2刀6毒9→D2狼4自爆，夜次明确。','supplemental为空，无其他槽补9死亡。','D3真实票权名单排除9，旁证支持9此前已出局，不推定其后仍有票权。'])
add(4,'BV18Bhn6dEJ6','D2夜死targets漏1，与自身双死说明矛盾','P1',[change('BV18Bhn6dEJ6',2,'day','night_deaths',[1,6],'targets')],[(5253500,5275000)],'N2狼1自刀、毒6，一六双死；正式result已写双死，targets只[6]。',['魔术师N2换7/10、诡术师换9/11，均不涉及1/6；不是交换后的实际死者差异。','D1定序重投8出局、D2狼队交牌链明确；补充仅终局交牌，无1死亡另槽补齐。'])
add(5,'BV1MneS6kEWz','已在N3死亡守卫3仍被写为N4守1','P2',[change('BV1MneS6kEWz',4,'night','guard',{'action':'unavailable','actor':3,'targets':[],'availability':'dead','result':'守卫3已于N3死亡，无N4行动资格。'})],[(5963500,5978500)],'N3守1、刀3守卫单死；D3狼5爆后N4刀8，无守卫操作。正式N4重复N3守1。',['N3guard有效，因为行动后才死亡；不能把N3也删。','正式D3night_deaths=[3]，不是只靠字幕漏提推断。','机械狼11学习9号狼人、为机械双刀狼，不是机械守卫借用slot；当前N4actor也是3。'])
add(6,'BV1nJer63EDh','守7属于N2而非首夜','P2',[change('BV1nJer63EDh',1,'night','guard',{'action':'pass','actor':3,'targets':[]}),change('BV1nJer63EDh',2,'night','guard',{'action':'guard','actor':3,'targets':[7]})],[(3742000,3775000)],'复盘首夜“首位技能通过”接刀3救3，D1狼10爆后“守位守护7号预言家”；当前首夜写守7，N2未知。',['开局夜与D1之后夜明确分开，3守卫N2被刀并不否定当晚先守7。','首夜空过的字幕“通过”存在ASR消歧缺口，故该动作候选不冒充原音确认；N2守7定位较强。'],confidence='medium_high_text_asr_word_ambiguity',gaps=['首夜pass字词需原音/夜间原操作消歧；当前正式守7归错夜仍有连续复盘支持。'])
for num,id,targets,windows in [(7,'BV1g1YU6kERd',{3:2,4:3},[(4485000,4493000),(4505000,4516000)]),(8,'BV1nJer63EDh',{3:8,4:12},[(3780000,3788500),(3801000,3809000),(3820000,3843000)])]:
 add(num,id,'白泽尝试清标无事发生，却记result=cleared','P2',[change(id,n,'night','whiteze_clear_mark','no_effect（尝试清标目标保留；当时未成功移除标记）','result') for n in targets],windows,'法官明确“清除…无事发生”；当前cleared把操作目标等同于有效结果。',['不删除白泽真实尝试目标；行动和实际效果应分开。','当夜后续九尾新标记不能反证此前清标已成功，需按行动顺序读。','不依理论推导额外猎杀；保留现场唯一结算与终局。'],kind='action_vs_effect_conflict')
add(9,'BV12sY36hEdr','首夜12已死亡却记平安，并在D3错误扩成一张投票','P1',[change('BV12sY36hEdr',1,'day','night_deaths',{'action':'die','targets':[12],'result':'首夜守救同目标，法官明确宣布12倒牌。'}),{'field':'voting.ballot-2.eligible_voters/votes','formal_path':str((F['BV12sY36hEdr']/'voting.json').relative_to(E)),'formal_sha256':sha(F['BV12sY36hEdr']/'voting.json'),'formal_current_value':V['BV12sY36hEdr']['ballots'][1],'candidate_value':{'eligible_voters':[1,2,3,4,10,11],'votes_remove_only':[{'voter':12,'target':11,'state':'cast'}],'retain_other_observed_votes_and_winner':True},'applied':False}],[(1436000,1473000),(3537000,3557000),(3577000,3592000)],'首夜守12/刀12/救12，法官在首轮警长唱票后宣布12昨夜倒牌并请遗言。D3字幕只11投3，其余投11，正式用错误存活补集生成12→11。',['D1警下12→8发生在1454670，死亡1463640才宣布；保留其真实警徽票，不机械删除全部12投票。','本轮目视D3原保存图12被死亡图标覆盖，存活1/2/3/4/10/11；图不能单独确定首夜时点。','不是仅用守救同目标规则推论死亡，而是现场宣布+末复盘+后续图三条链。','mapping已确认公开和API没有隐藏修正，见../mapping/candidate-BV12sY36hEdr-propagation.json；属于源候选传播，不重复计作映射缺陷。'],confidence='high_text_plus_targeted_saved_frame',extras=[fileanchor(E/'data/extractions/S23/speech_frames/BV12sY36hEdr/BV12sY36hEdr_03484.980.png','t=3484980ms','本轮目视，D3座12已死；现场宣告才是N1定位依据。')])
add(10,'BV1KBhU68EjA','D3夜死汇总漏舞者12','P2',[change('BV1KBhU68EjA',3,'day','night_deaths',[9,12],'targets')],[(5524000,5544000)],'N3舞池少数方12被舞出局，再刀9女巫，法官复盘9/12双死；正式夜死result也写9/12，但targets只9。',['dance_resolution已记12死亡，故这是汇总遗漏，不说整局完全没有12出局记录。','D3两轮票权均排除12，不会据此新增/删除一张真实投票。','原因仍区分舞出局与狼刀，不能将12记作狼刀。'],kind='death_aggregate_incomplete')
add(11,'BV1K3aQ6zEB9','终局查验说明误称6通灵师N2已死','P2',[change('BV1K3aQ6zEB9',3,'night','seer_check','N3狼队夜间交牌终局，后续查验未观察；不能称6号N2已死。','result')],[(3816500,3853500)],'N2守6挡刀、仅11毒死；N3交牌。因此当前unavailable理由“6已在N2出局”错误，是否未知/不可用编码另按终局规范，不补目标。',['正式N2guard与night_deaths也确认6活、11单死。','N3之后未开始D3，网站伪造D3无放逐由mapping单列。','保留已确认终局边界，不因模板未知补后续查验或强制pass。'],kind='wrong_explanation_not_new_action')
add(12,'BV123aQ6BEu2','N2再次学习8疑为首夜学习重复','P3',[change('BV123aQ6BEu2',2,'night','mechanical_action',{'action':'unknown','actor':9,'targets':[],'note':'N1学习8保留；N2是否有解锁技能实际使用未由复盘给出，不凭重复学习造动作。'})],[(2096000,2129000)],'连续复盘只N1学8，N2讲守4/刀3/毒8/验9，不再学。正式N1/N2均learn8，疑重复。',['机械狼一个学习结果、后续分支技能；docs10及模板仅用作约束，不当作本局观察成功。','有可能旧字段想表达学习形态持续，而非再次行动；需先明确slot语义，故列P3候选，不直接删。'],confidence='medium_semantic_duplicate_candidate',kind='possible_duplicate_event',extras=[fileanchor(E/'docs/10_版型规则与夜间顺序.md','机械狼通灵师','规则约束，不替代本局行动证据。')])
add(13,'BV1zmpB6PEWL','4号警长移徽12被提前重复写在D1','P2',[change('BV1zmpB6PEWL',1,'day','badge',{'action':'unknown','targets':[],'note':'D1无已观察到移徽；4号持徽。D2 4死后移12保留。'})],[(5630000,5649000)],'D1当选4、放逐9；N2刀4毒1，4死才移12。当前D1与D2都transfer12。',['D2移徽原记录正确，不能全删。','D1死亡9并非警长4，不能以9出局解释移徽。','替代事件持徽是状态，不擅自造一个模板不支持的hold动作。'])
add(14,'BV1zmpB6PEcF','通灵查验反馈将临时平民误写实际盗宝底牌','P2',[change('BV1zmpB6PEcF',1,'night','seer_check','平民','result')],[(6064500,6075000)],'盗宝8首夜选平民；法官明说查验8盗宝大师“为平民身份”。通灵结果应平民而非盗宝大师，真实底牌8仍盗宝大师。',['N2改选摄梦人，通灵再次验8得到摄梦人，正式第二夜正确，恰好验证动态反馈机制。','不改变10/13g2用户DQ定案：末狼8 DQ刀失效、平安夜及后来真实D3票均保留。'],kind='actual_check_feedback_conflict')
add(15,'BV1V8af6zE5T','D2出现第二次5号当选警长，疑首日结果重复','P3',[change('BV1V8af6zE5T',2,'day','sheriff_result',{'action':'unknown','targets':[],'note':'5号继续持徽状态保留；D2再选警长未观察。'})],[(4300000,4500000)],'D1两轮警长票选5，D2无重选，正式D1 elected5且D2又elected5。',['本局D1警徽初选/PK两轮真实投票保留，不把PK误当D2。','若该slot被有意当“当前警长”快照，则应展示继任状态而非新当选事件；列语义候选需澄清。'],confidence='medium_semantic_duplicate_candidate',kind='possible_duplicate_event')
# Use exact final recap rather than an arbitrary earlier broad window for the preceding duplicate.
findings[-1]['source_evidence']=[anchor('BV1V8af6zE5T',**{'a':G['BV1V8af6zE5T']['recap']['window']['start_ms'],'b':G['BV1V8af6zE5T']['recap']['window']['end_ms']})]
add(16,'BV1nJer6gEkx','D4猎人开枪带7被同时计入夜死汇总','P3',[change('BV1nJer6gEkx',4,'day','night_deaths',[12],'targets')],[(4305000,4340000)],'N4狼刀12猎人，12出局后开枪7；正式night_deaths=[12,7]且hunter_shot=12→7。死亡事实不争议，争议是夜死汇总混入后续枪杀。',['保留12开枪7及两人投票前已死，不把7恢复票权。','若night_deaths被有意定义为天亮整个技能链死亡汇总，则需保留双死但明确枪杀原因；不能机械改字段。'],confidence='medium_field_semantics_candidate',kind='death_phase_classification')
# Per-game explicit actual-check feedback candidates, limited to the 19 pure physical-role results.
feedback_games=[]
for id,g in G.items():
 if not any(s['role']=='预言家' for s in D[id]['seats']):continue
 changes=[];matched=[]
 for r in D[id]['rounds']:
  for e in r['night']:
   result=str(e.get('result'))
   if e['slot']=='seer_check' and e['action']=='check' and '好人' not in result and any(w in result for w in ['平民','猎人','白神','女巫','白泽','守卫']):changes.append(change(id,r['number'],'night','seer_check','好人（目标真实身份另存，不当作预言家具体身份反馈）','result'))
 if not changes:continue
 for i,row in enumerate(g['recap']['rows']):
  if '验证' in row['text'] or '查验' in row['text']:
   chunk=g['recap']['rows'][max(0,i-1):i+3]
   if '好人' in ''.join(x['text'] for x in chunk):matched.append(anchor(id,chunk[0]['start_ms'],chunk[-1]['end_ms']))
 if not matched:raise RuntimeError('feedback no direct source '+id)
 x=add(17,id,'预言家实际好人反馈被写为具体底牌（同类逐局子项）','P2',changes,[],'法官措辞“查验某号[底牌]为好人身份”；正式result仅具体底牌，混淆全知复盘与行动者得到的信息。',['目标、底牌及整局胜负保持不变；并非说查验目标错误。','只纳入result完全不含好人的19个字段；“好人（底牌…）”等明确分离字段不报错。','字段规范明确实际查验反馈独立于底牌；若公开result只是全知摘要，应改文案/字段解释而非改变底牌。'],kind='actual_check_feedback_conflict');x['id']='S23-F17-'+id;x['source_evidence']=matched;feedback_games.append(id)
# Operational cross-checks delegated to mapping; no duplicate counts as source-candidate findings.
mapping_links={
'BV1gBhn6dE5c':['最后神11猎人D4放逐立即终局，无后续枪窗；源unknown不是主动不开枪。','D1放逐12号默认弃票basis发布丢失。'],
'BV1K3aQ6zEB9':['N3夜间交牌、D3未开始；展示造D3无人放逐。'],
'BV123aQ6BEu2':['N3夜间交牌、D3未开始；展示造D3无人放逐。'],
'BV1BmpB6PE2C':['猎人8 N2错误摘盔DQ，D2宣布；supplemental已有，后续N3/4/5展示能开枪不成立。'],
'BV1UNaQ6kEWR':['D1警徽1/2/7/10/11默认弃票basis发布丢失。']}
for x in findings:
 for c in x['changes']:c['locator_semantics']='rounds[n]按round.number的游戏轮次、seats[n]按seat的座号定位，不是零起始JSON数组下标；候选不可直接当JSON Patch执行。'
 daily=read(E/x['prior_review']['path']);related=[]
 for i,r in enumerate(daily.get('finding_resolutions',[])):
  if any(e.get('source_path')==a['path'] and e.get('start_ms',-1)<a['end_ms'] and e.get('end_ms',-1)>a['start_ms'] for e in r.get('evidence',[]) for a in x['source_evidence']):related.append({'locator':'/finding_resolutions/'+str(i),'record':r})
 x['prior_resolution_records_overlapping_source_windows']=related
 x['prior_review_independence_note']='这些归档审计与本轮原字幕复核可能来自同一来源，并非独立新媒体证据。confirmed标签不等于用户逐字段确认；未发现本候选字段有明确用户反向定案。'
manual=[]
for i,g in enumerate(A['games'],1):
 id=g['bvid'];related=[x for x in findings if x['bvid']==id];m={'ordinal':i,'bvid':id,'game_id':g['game_id'],'date':g['date'],'game_number':g['game_number'],'board':g['board'],'source':g['source'],'recap_window':g['recap']['window'],'manual_semantic_reading':{'performed_by':'AI_semantic_reading_not_human_review','status':'completed_final_recap_only','actually_read':'最终法官复盘窗口逐句对照12座身份/个人阵营/胜方、全部已知事件、夜次/终局。必要候选另读对局中宣告/原图，详见发现。','not_claimed':['未逐句读完全场所有话轮','未观看75局完整视频','未回听原音','未逐张重新语义读178票轮所有唱票或300狼位全部悍跳话轮']},'formal_scope_counts':g['counts'],'candidate_ids':[x['id'] for x in related],'mapping_crosslinks':mapping_links.get(id,[]),'source_conflict_status':'has_candidates' if related else 'no_new_conflict_found_within_read_scope','direct_saved_frames_viewed':[],'unknown_event_slots_preserved':g['counts']['unknown_event_slots'],'gap':'复盘省略的事件/细票/特殊资格保持未知或原旁证；没有新候选不等于全字段原媒体核验通过。'}
 for x in related:
  for e in x['extra_evidence']:
   if e.get('path','').endswith('.png') and e not in m['direct_saved_frames_viewed']:m['direct_saved_frames_viewed'].append(e)
 manual.append(m);g['manual_semantic_audit']=m;g['semantic_candidate_ids']=m['candidate_ids'];g['mapping_crosslinks']=m['mapping_crosslinks']
 for f in g['field_checks']:
  matches=[{'candidate_id':x['id'],'change':c} for x in related for c in x['changes'] if c['field']==f['field'] or c['field'].startswith(f['field']+'.')]
  if matches:f['semantic_candidate_changes']=matches;f['conclusion']='semantic_source_conflict_candidate_not_applied'
  elif f['conclusion']=='retained_no_change_proposed':f['conclusion']='no_new_candidate_on_this_field_within_limited_scope_not_raw_media_verified'
counts=collections.Counter(x['priority'] for x in findings);summary={'formal_ref':REF,'audit_target':'user_designated_published_source_snapshot_not_live_production_url','reader':'AI_semantic_reading_not_human_review','games':75,'manual_final_recap_games':len(manual),'manual_entire_transcript_games':0,'original_audio_relistened_games':0,'direct_original_saved_frames_viewed':3,'direct_original_saved_frame_games':3,'semantic_candidate_records':len(findings),'semantic_issue_groups':17,'candidate_games':len(set(x['bvid'] for x in findings)),'candidate_fields':sum(len(x['changes']) for x in findings),'candidate_records_by_priority':dict(counts),'feedback_subcategory_games':len(feedback_games),'feedback_subcategory_fields':sum(len(x['changes']) for x in findings if x['id'].startswith('S23-F17-')),'machine_anomalies_after_accounting_for_preserved_metadata':len(read(B/'candidate_anomalies.json')),'candidate_status':'all candidate_only_not_applied','machine_stats':dict(sum((collections.Counter(g['counts']) for g in G.values()),collections.Counter()))}
write(B/'semantic_findings.json',{'summary':summary,'findings':findings});write(B/'manual_semantic_coverage_75.json',manual);write(B/'per_game_audit.json',A);write(B/'summary.json',summary)
with (B/'per_game_summary.csv').open('w',newline='') as f:
 w=csv.writer(f);w.writerow(['序号','日期','局序','BVID','game_id','版型','胜方','AI语义复盘状态','复盘起毫秒','复盘止毫秒','候选ID','已知槽','未知槽','票轮','逐票条数','原图直核数','源SHA256'])
 for m in manual:
  g=G[m['bvid']];w.writerow([m['ordinal'],m['date'],m['game_number'],m['bvid'],m['game_id'],m['board'],g['winner'],m['manual_semantic_reading']['status'],m['recap_window']['start_ms'],m['recap_window']['end_ms'],';'.join(m['candidate_ids']),g['counts']['known_event_slots'],g['counts']['unknown_event_slots'],g['counts']['ballots'],g['counts']['votes'],len(m['direct_saved_frames_viewed']),g['source']['sha256']])
# Complete inventory includes earlier materialized source texts plus the three frames and rule/doc blobs.
treeout=subprocess.check_output(['git','-c','core.quotePath=false','ls-tree','-r',REF],cwd=R,text=True);tree={p:m.split()[2] for m,p in (r.split('\t',1) for r in treeout.splitlines())}
manifest=[]
for p in sorted(E.rglob('*')):
 if p.is_file():
  rel=str(p.relative_to(E));manifest.append({'path':rel,'git_blob':tree.get(rel),'sha256':sha(p),'bytes':p.stat().st_size,'kind':'saved_original_frame_directly_viewed' if p.suffix=='.png' else 'text_evidence'})
write(B/'complete_evidence_manifest.json',manifest)
# Readable report, detailed snippets below provide stable exact windows; raw evidence never gets silently replaced.
lines=['# S23 已上线数据逐局字段语义审计','',f'正式基线：`{REF}`。范围：S23 正赛 75 局。只读审计；未改正式数据、未推送、未部署。','',
'## 结论与覆盖边界','',
'“已上线”仅指用户指定的发布源快照；本轮未访问生产URL，不宣称实时生产页面核验。所有阅读/目视均由AI完成，不是新增真人审核。',
'字段路径 `rounds[n]` 指round.number轮次、`seats[n]` 指seat座号，并非可执行JSON数组下标；这些候选不可直接apply。','',f'- 已由AI逐段语义阅读（非仅程序匹配） **75/75 局最终法官复盘窗口** 并对照当前字段；不等于75局全视频、全音频或整局所有话轮已核。',
f'- 候选共 **{len(findings)}条记录、17类问题、涉及{summary["candidate_games"]}局、{summary["candidate_fields"]}个字段/字段组**；均未应用。P1 {counts["P1"]}、P2 {counts["P2"]}、P3 {counts["P3"]}。同类预言家反馈为13局19字段，逐局独立记录。',
'- 本轮直接目视 **3张已保存原图/3局**，未回听原音。混血4→8另经root对同图及字幕独立复核。原图不是本轮播放原视频。',
'- 75份原字幕/ASR来源SHA均与entry绑定一致（72平台字幕、3 FunASR）。逐字段机器记录含900座、227轮、4390槽（1578已知、2812未知）、178票轮、1300逐票条目。',
'- 机器检索/源内一致性：4593证据对象中3708条本局字幕引文逐时间窗全文匹配，43条其他文本匹配；840条媒体/其他源未读，2条其他文本为转述而非逐字引文。引文相等不是事实已被原媒体证实。58处初看patch差异实为扩展metadata保存于formal_context，不算事实错。',
'- `unknown`保持未知；模板空槽不等于2812项待用户确认。2项终局未观察查验保留既有接受状态。','',
'## 最高影响候选','',
'1. **9/24 g1 BV1KaaT67Eca**：混血4应混8狼人而非12预言家；实际底牌仍混血儿、全局好人胜不变。条件重算荣耀单局由胜+1变负−1，S23总分3→1（仅候选重算，不改榜）。',
'2. **9/11 g2 BV1g1YU6kERd**：首夜平安、N2一五双死，被写成D1死1/D2死8；法官对局中连续宣布已支持，非夜次映射误读。',
'3. **9/15 g1 BV1theH6cESW**：六九双死只记6；有现场法官字幕“6号九号倒牌”。',
'4. **9/22 g2 BV18Bhn6dEJ6**：一六双死只记6，自身说明已与targets冲突；交换未涉及1/6。',
'5. **9/10 g4 BV12sY36hEdr**：首夜12明确倒牌却记平安，D3又用“其余玩家”补成12投11。首日真实警徽票12→8发生在宣布死亡前，应保留。','',
'## 用户定案与历史记录优先级','',
'- 10/9 g3 BV1U3p86dEJY：10号遗言不计常规悍跳，6号悍跳保留。旧formal_rules pending及早期报告不覆盖最新用户定案与发布结果。',
'- 最新悍跳发布75局/300物理狼位：82 yes、218 no、0 uncertain，24成功、0待核。此为最新发布/旁证核对，不声称本轮重看300狼位视频。',
'- 末神猎人出局即终局、无枪窗；不写主动不开枪。10/13 g2末狼8 DQ狼刀失效、平安夜及随后实际票轮保留。',
'- 2个已接受的not_observed终局查验：BV1sAYJ6UEoF N3、BV1MheH6wEBb N3。不重开成用户必须回答项。','',
'## 与发布映射审计衔接','',
'映射缺陷由 `../mapping/` 独立报告，此处不重计为源事实错误：BV1gBhn6dE5c末神枪窗、两局10/2 N3交牌后伪造D3、BV1BmpB6PE2C猎人8 DQ后枪资格，以及6条默认弃票basis丢失。详见本目录逐局mapping_crosslinks。','',
'## 候选逐项双向链','']
for x in findings:
 lines += [f'### {x["id"]} · {x["date"]} 第{x["game_number"]}局 · {x["bvid"]}',f'**{x["title"]}**（{x["priority"]}；{x["confidence"]}；未修改）','',x['reasoning'],'','| 字段 | 正式现值 | 候选值 |','|---|---|---|']
 for c in x['changes']:
  fmt=lambda o:json.dumps(o,ensure_ascii=False,separators=(',',':')).replace('|','\\|')
  lines.append(f'| `{c["field"]}` | `{fmt(c["formal_current_value"])}` | `{fmt(c["candidate_value"])}` |')
 lines += ['','证据：']
 for e in x['source_evidence']:
  lines += [f'- `{e["path"]}`，{e["start_ms"]}–{e["end_ms"]} ms，SHA256 `{e["sha256"]}`。',f'  > {e["quote"].replace(chr(10)," / ")}']
 lines += ['','反证/替代解释检查：']+['- '+s for s in x['alternative_explanations_checked']]+['','缺口：'+'；'.join(x['remaining_gap']),'']
lines += ['## 75局逐局覆盖表','','每局完整字段/旧值/候选/证据见 `per_game_audit.json`；本表仅导航。不列候选只表示本轮限定阅读范围未发现新冲突。','','| 序号 | 日期/局 | BVID | 复盘毫秒窗 | 候选 | 已知/未知槽 | 票轮 |','|---|---|---|---|---|---|---|']
for m in manual:lines.append(f'| {m["ordinal"]} | {m["date"]} g{m["game_number"]} | {m["bvid"]} | {m["recap_window"]["start_ms"]}–{m["recap_window"]["end_ms"]} | {", ".join(m["candidate_ids"]) or "限定范围未发现新冲突"} | {m["formal_scope_counts"]["known_event_slots"]}/{m["unknown_event_slots_preserved"]} | {m["formal_scope_counts"]["ballots"]} |')
lines += ['','## 文件与复现','', '- `semantic_findings.json`：29条候选逐项现值/候选、精确时间窗/字幕行、SHA、反证、缺口。','- `manual_semantic_coverage_75.json` / `per_game_summary.csv`：逐局AI语义阅读状态和范围。','- `per_game_audit.json`：全部75局字段机器记录、所有槽/票轮与旁证；已挂接语义候选。','- `complete_evidence_manifest.json`：全部本地审计证据的Git blob、SHA256、大小。','- `source_manifest.json`：75原始来源绑定核验。`evidence/`保留原字节。','- `audit.py`重建机器审计，`build_semantic_report.py`构建本报告和逐局语义关联。先后运行；不会写正式仓库。','- `artifact_checksums.sha256`：本目录非evidence输出SHA；不含校验清单自身。','', '停止条件：75局末复盘语义阅读、重点候选双向证据和高影响公开传播/条件影响已保存；尚未授权改正式事实或开展75局全媒体逐话轮重审。下一步须按候选优先级回听歧义原音或审批修正，不能将本审计作全事实验收通过。','']
(B/'S23_逐局字段语义审计.md').write_text('\n'.join(lines))
(B/'README.md').write_text('# S23 只读发布数据审计\n\n入口：[S23_逐局字段语义审计.md](S23_逐局字段语义审计.md)。\n\n保存地为本dot云端工作区；未推送/部署，未改正式数据。摘要见summary.json。\n\nAI语义覆盖75局最终复盘窗口，不是75局完整原视频核验。全部候选未应用，未知保持未知。\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
