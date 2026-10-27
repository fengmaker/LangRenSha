import pathlib,json,sys
B=pathlib.Path('/workspace/scratch/a7edd912716e/audit-published/S23');E=B/'evidence';allg=json.loads((B/'per_game_audit.json').read_text())['games'];start=int(sys.argv[1]);end=int(sys.argv[2])
for i,g in enumerate(allg[start-1:end],start):
 f=next((E/'data/games/S23').glob('*'+g['bvid']));d=json.loads((f/'dossier.json').read_text());print('\n#',i,g['date'],'g'+str(g['game_number']),g['bvid'],'winner',g['winner']);print('角色',','.join(str(s['seat'])+s['role']+('狼混' if s['role']=='混血儿' and s['faction']=='werewolf' else '') for s in d['seats']));print('原复盘', ''.join(x['text'] for x in g['recap']['rows']));
 for rr in d['rounds']:
  items=[]
  for ph in ['night','day']:
   for e in rr[ph]:
    if e['action']=='unknown':continue
    items.append(('N' if ph=='night' else 'D')+str(rr['number'])+':'+e['slot']+' '+e['action']+' '+str(e.get('actor') or '')+'→'+str(e.get('targets') or '')+('='+str(e['result'])[:35] if e.get('result') else ''))
  print('; '.join(items))
