(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('review-data').textContent);
  const format = 'masters-incremental-review-v2';
  const legacyFormat = 'masters-incremental-review-v1';
  const cards = new Map(Array.from(document.querySelectorAll('[data-review-id]'), card => [card.dataset.reviewId, card]));
  const status = document.getElementById('status');
  const keyFor = game => `${format}:${encodeURIComponent(data.season)}:${encodeURIComponent(game.review_id)}:${game.candidate_sha256}:${game.source_sha256}`;
  const oldKeyFor = (game, prefix) => `${prefix}:${encodeURIComponent(data.season)}:${encodeURIComponent(game.review_id)}:${game.candidate_sha256}:${game.source_sha256}`;
  const emptyBluffs = game => game.seats.map(seat => ({seat, decision:'', success:''}));
  const noBluffs = game => game.seats.map(seat => ({seat, decision:'no', success:''}));
  const isAllNo = rows => rows.every(row => row.decision === 'no');
  const rowsFor = card => Array.from(card.querySelectorAll('[data-bluff-row]'));
  const readCard = card => {
    if (card.querySelector('[data-no-bluff]').checked) {
      return {note:card.querySelector('[data-note]').value, reviewed:card.querySelector('[data-reviewed]').checked,
        bluffs:noBluffs(card.reviewGame)};
    }
    const bySeat = new Map(card.reviewBluffs.map(row => [row.seat,
      row.decision === 'yes' ? {seat:row.seat, decision:'', success:''} : {...row}]));
    for (const row of rowsFor(card)) {
      const seat = Number(row.querySelector('[data-bluff-person]').value);
      if (seat) bySeat.set(seat,{seat, decision:'yes', success:row.querySelector('[data-bluff-success]').value});
    }
    return {note:card.querySelector('[data-note]').value, reviewed:card.querySelector('[data-reviewed]').checked,
      bluffs:Array.from(bySeat.values())};
  };
  const updateRows = card => {
    const rows = rowsFor(card);
    const noBluff = card.querySelector('[data-no-bluff]').checked;
    const selected = new Set(rows.map(row => row.querySelector('[data-bluff-person]').value).filter(Boolean));
    for (const row of rows) {
      const person = row.querySelector('[data-bluff-person]');
      for (const option of person.options) option.disabled = !!option.value && selected.has(option.value) && option.value !== person.value;
      person.disabled = noBluff;
      row.querySelector('[data-bluff-success]').disabled = noBluff || !person.value;
      row.querySelector('[data-remove-bluff]').disabled = noBluff || (rows.length === 1 && !person.value);
    }
    card.querySelector('[data-add-bluff]').disabled = noBluff || rows.length >= card.reviewBluffs.length;
    const other = noBluff ? [] : card.reviewBluffs.filter(row => ['no','uncertain'].includes(row.decision));
    const summary = card.querySelector('[data-other-bluff-decisions]');
    summary.hidden = other.length === 0;
    summary.textContent = other.map(row => `${row.seat}号：${row.decision === 'no' ? '未悍跳' : '悍跳待定'}`).join('；');
  };
  const addRow = (card, item) => {
    const row = card.querySelector('[data-bluff-row-template]').content.firstElementChild.cloneNode(true);
    row.querySelector('[data-bluff-person]').value = item ? String(item.seat) : '';
    const success = row.querySelector('[data-bluff-success]');
    success.value = item?.success || ''; success.disabled = !item;
    card.querySelector('[data-bluff-rows]').append(row);
  };
  const writeCard = (card, value) => {
    card.querySelector('[data-note]').value = value.note;
    card.querySelector('[data-reviewed]').checked = value.reviewed;
    card.reviewBluffs = value.bluffs.map(row => ({...row}));
    card.querySelector('[data-no-bluff]').checked = isAllNo(value.bluffs);
    card.querySelector('[data-bluff-rows]').replaceChildren();
    const selected = value.bluffs.filter(row => row.decision === 'yes');
    for (const item of selected) addRow(card,item);
    if (!selected.length) addRow(card);
    updateRows(card);
  };
  const saveCard = (game, card) => {
    const value = readCard(card);
    card.reviewBluffs = value.bluffs;
    updateRows(card);
    try { localStorage.setItem(keyFor(game),JSON.stringify(value)); status.textContent='本局意见和选择已保存。'; }
    catch (_) { status.textContent='浏览器无法保存草稿，请导出意见。'; }
  };
  const validBluffs = (rows, game) => Array.isArray(rows) && rows.length === game.seats.length &&
    new Set(rows.map(row => row && row.seat)).size === rows.length && rows.every(row => row &&
      Object.keys(row).sort().join('|') === 'decision|seat|success' && game.seats.includes(row.seat) &&
      ['', 'yes','no','uncertain'].includes(row.decision) && ['', 'success','failure','uncertain'].includes(row.success) &&
      (row.decision === 'yes' || row.success === ''));
  for (const game of data.games) {
    const card = cards.get(game.review_id);
    card.reviewGame = game;
    writeCard(card,{note:'',reviewed:false,bluffs:emptyBluffs(game)});
    try {
      let saved = JSON.parse(localStorage.getItem(keyFor(game)) || 'null');
      if (!saved) for (const prefix of [legacyFormat,'masters-simple-review-sample']) {
        const old = JSON.parse(localStorage.getItem(oldKeyFor(game,prefix)) || 'null');
        if (old) { saved={...old,bluffs:emptyBluffs(game)}; break; }
      }
      if (saved && typeof saved.note === 'string' && typeof saved.reviewed === 'boolean' && validBluffs(saved.bluffs,game)) writeCard(card,saved);
    } catch (_) { status.textContent='部分草稿未能读取，可导入此前导出的意见。'; }
    card.querySelector('[data-note]').addEventListener('input',()=>saveCard(game,card));
    card.addEventListener('change',event=>{
      if (event.target.matches('[data-no-bluff]')) {
        const value = readCard(card);
        value.bluffs = event.target.checked ? noBluffs(game) :
          (isAllNo(value.bluffs) ? emptyBluffs(game) : value.bluffs);
        writeCard(card,value);
      }
      if (event.target.matches('[data-bluff-person]')) {
        const success=event.target.closest('[data-bluff-row]').querySelector('[data-bluff-success]');
        success.disabled=!event.target.value;
        success.value='';
      }
      saveCard(game,card);
    });
    card.querySelector('[data-add-bluff]').addEventListener('click',()=>{addRow(card);updateRows(card);});
    card.addEventListener('click',event=>{
      const remove=event.target.closest('[data-remove-bluff]');
      if (!remove) return;
      remove.closest('[data-bluff-row]').remove();
      if (!rowsFor(card).length) addRow(card);
      saveCard(game,card);
    });
  }
  const picker=document.getElementById('game-picker');
  for (const game of data.games) { const option=document.createElement('option'); option.value=game.review_id; option.textContent=game.label; picker.append(option); }
  let active=0;
  const showGame=index=>{
    active=Math.max(0,Math.min(data.games.length-1,index));
    data.games.forEach((game,i)=>cards.get(game.review_id).hidden=i!==active);
    picker.value=data.games[active]?.review_id || '';
    document.getElementById('previous-game').disabled=active===0;
    document.getElementById('next-game').disabled=active===data.games.length-1;
    document.getElementById('game-navigation').hidden=data.games.length<2;
  };
  picker.addEventListener('change',()=>showGame(data.games.findIndex(game=>game.review_id===picker.value)));
  document.getElementById('previous-game').onclick=()=>showGame(active-1);
  document.getElementById('next-game').onclick=()=>showGame(active+1);
  showGame(0);
  document.getElementById('export').addEventListener('click',()=>{
    const payload={format,season:data.season,games:data.games.map(game=>{
      const {seats,label,...identity}=game; return {...identity,...readCard(cards.get(game.review_id))};
    })};
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'});
    const url=URL.createObjectURL(blob), anchor=document.createElement('a');
    anchor.href=url; anchor.download=`${data.season}_逐局复核意见.json`; anchor.click(); URL.revokeObjectURL(url);
    status.textContent='已导出本页全部对局的意见和悍跳选择。';
  });
  document.getElementById('import-file').addEventListener('change',async event=>{
    const file=event.target.files && event.target.files[0]; if (!file) return;
    let payload;
    try { payload=JSON.parse(await file.text()); }
    catch (_) { status.textContent='导入失败：不是有效JSON。'; event.target.value=''; return; }
    const errors=[], accepted=[], seen=new Set(), current=new Map(data.games.map(game=>[game.review_id,game]));
    if (![format,legacyFormat].includes(payload?.format) || payload?.season!==data.season || !Array.isArray(payload?.games)) errors.push('格式或赛季不匹配');
    for (const item of Array.isArray(payload?.games)?payload.games:[]) {
      const game=current.get(item?.review_id);
      if (!game || seen.has(item.review_id)) {errors.push('包含未知或重复对局');continue;}
      seen.add(item.review_id);
      if (['bvid','cid','page','candidate_sha256','source_sha256'].some(key=>item[key]!==game[key])) errors.push('对局或候选版本不匹配');
      if (typeof item.note!=='string' || typeof item.reviewed!=='boolean') errors.push('意见字段无效');
      const bluffs=payload.format===legacyFormat?readCard(cards.get(game.review_id)).bluffs:item.bluffs;
      if (!validBluffs(bluffs,game)) errors.push('悍跳座位或选择不正确');
      accepted.push({game,value:{note:item.note,reviewed:item.reviewed,bluffs}});
    }
    if (errors.length) {status.textContent=`导入未完成：${[...new Set(errors)].join('；')}。没有修改任何草稿。`;event.target.value='';return;}
    const previous=[];
    try {
      for (const {game} of accepted) previous.push({key:keyFor(game),value:localStorage.getItem(keyFor(game))});
      for (const {game,value} of accepted) localStorage.setItem(keyFor(game),JSON.stringify(value));
    } catch (_) {
      for (const row of previous) try {if(row.value===null)localStorage.removeItem(row.key);else localStorage.setItem(row.key,row.value);} catch (_) {}
      status.textContent='导入未完成：无法保存全部草稿。';event.target.value='';return;
    }
    for (const {game,value} of accepted) writeCard(cards.get(game.review_id),value);
    status.textContent=`已导入${accepted.length}局；未列出的对局保持原样。`; event.target.value='';
  });
  const dialog=document.getElementById('image-dialog');
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-enlarge]');
    if (button) {document.getElementById('large-image').src=button.querySelector('img').src;dialog.showModal();}
  });
  document.getElementById('close-image').onclick=()=>dialog.close();
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
})();
