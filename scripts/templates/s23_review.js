'use strict';
(() => {
  const data = window.__S23_REVIEW__;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '待核').replace(/[&<>"']/g, x => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const key = 's23-game-review:' + data.snapshot_id;
  let feedback = {kind:'S23_game_review_feedback_v1',snapshot_id:data.snapshot_id,reviewer:'',games:{}};
  let current = data.games[0]?.entry.bvid;
  const stateLabels = {pending:'尚未确认',accept:'同意本局候选',correction:'本局有更正',unsure:'仍不确定'};
  const faction = {good:'好人',werewolf:'狼人',third_party:'第三方'};
  const action = {unknown:'原文未说明',unavailable:'本轮不适用',pass:'空过',attack:'击杀',save:'用解药',poison:'用毒',check:'查验',learn:'学习',guard:'守护',choose:'选择',shoot:'开枪',die:'出局',peaceful:'平安夜',exile:'放逐',self_destruct:'自爆',elected:'当选警长',transfer:'移交警徽',badge_lost:'警徽流失',deferred:'延期竞选',not_held:'未举行',none:'无',exchange:'交换',order:'发言顺序',not_carrying:'尚未接刀',carrying:'接刀',can_shoot:'可以开枪',cannot_shoot:'不能开枪',register:'报名',continued:'继续竞选'};
  Object.assign(action,{forbidden:'规则禁止',mark:'标记',clear_mark:'清除标记',clear:'清除标记',hunt:'发动猎杀时刻',kill:'击杀',attempt:'尝试发动',surrender:'认输',swap:'交换',vote:'投票',death:'出局',destroy:'撕毁警徽',disqualify:'判离（DQ）'});
  Object.assign(action,{verify:'验证',give_mask:'扣面具',dance:'共舞',minority_dies:'少数方出局'});
  function time(ms){let s=Math.floor((ms||0)/1000);return [Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(v=>String(v).padStart(2,'0')).join(':');}
  function currentGame(){return data.games.find(g=>g.entry.bvid===current);}
  function learningInfo(game,seat){
    const target=seat.role==='混血儿'?game.seat_models?.[seat.seat]:seat.learning_target;
    return target?`<small>${seat.role==='混血儿'?'榜样':'模仿目标'} ${esc(target)}号；${esc(seat.learned_role||(seat.role==='混血儿'?'榜样身份见座位表':'形态待核'))}</small>`:'';
  }
  function record(bvid){return feedback.games[bvid] || {bvid,status:'pending',comment:'',questions:{}};}
  function persist(){
    try{localStorage.setItem(key,JSON.stringify(feedback));$('status').textContent='已暂存于当前浏览器；导出文件后交回复核。';}
    catch{ $('status').textContent='浏览器不能暂存，请及时导出意见文件。'; }
  }
  try{const old=JSON.parse(localStorage.getItem(key));if(old?.snapshot_id===data.snapshot_id)feedback=old;}catch{}
  $('reviewer').value=feedback.reviewer||'';
  function link(path,label){return path?`<a href="${esc(path)}" target="_blank" rel="noopener">${esc(label)}</a>`:'';}
  function evidence(proof){
    return (Array.isArray(proof)?proof:[]).map(p=>{
      if(p.kind==='user_confirmation'||/用户确认/.test(p.source_path||''))return `<div class="evidence"><span class="muted">用户确认</span> ${link(p.file_url,'查看确认记录')}<blockquote>${esc(p.quote||p.reasoning||'')}</blockquote></div>`;
      const start=p.start_ms??p.frame_time_ms??0;
      const visual=p.kind==='video_frame'||/\.(png|jpe?g)$/i.test(p.source_path||'');
      return `<div class="evidence"><span class="muted">${visual?'画面':'原文'} ${time(start)}</span> ${visual?link(p.file_url,'打开画面'):`<button data-seek="${start}">听这一段</button>`} ${link(`https://www.bilibili.com/video/${esc(current)}/?t=${Math.floor(start/1000)}`,'视频定位')}<blockquote>${esc(p.quote||p.reasoning||'来源见对应文件')}</blockquote></div>`;
    }).join('');
  }
  function eventText(e){
    const who=e.actor?`${e.actor}号 `:'';
    const targets=(e.targets||[]).map(n=>`${n}号`).join('、');
    const label=data.slot_labels[e.slot]||e.slot;
    const actionLabel=e.invalidated?'判定失效':e.blocked_by_game_end?'对局结束，无法发动':action[e.action]||e.action;
    return `<div class="event ${e.action==='unknown'?'unknown':''}"><b>${esc(label)}</b>：${esc(who)}${esc(actionLabel)}${targets?' → '+esc(targets):''}${e.result?'；'+esc(e.result):''}${e.resolved_targets?.length?'；实际 '+esc(e.resolved_targets.join('、'))+'号':''}${e.inferred?`<div class="muted">规则推导：${esc(e.inference_note||'依据已知身份与前序事件推导，保留原候选记录。')}</div>`:''}</div>`;
  }
  function ballots(game,day){
    return (game.voting.ballots||[]).filter(b=>b.day===day).map(b=>{
      const title=(b.kind==='sheriff'?'警徽票':'放逐票')+' · '+(b.stage==='pk'?'PK轮':b.stage==='revote'?'技能重投':b.stage==='initial'?'初始轮':b.stage||'投票轮')+' '+(b.number||'');
      const rows=(b.votes||[]).map(v=>`<tr><td>${esc(v.voter)}号</td><td>${v.state==='abstained'?'弃票':esc(v.target)+'号'}</td></tr>`).join('');
      const status=b.status==='complete'?'本轮逐人票型已记录':b.status==='partial'?'票权或记录待核实':'本轮待核实';
      return `<details open><summary><b>${esc(title)}</b> · ${b.winner?'结果 '+esc(b.winner)+'号':b.tied_candidates?.length?'平票 '+esc(b.tied_candidates.join('、'))+'号':'结果待核实'}</summary><p class="muted">候选 ${esc((b.candidates||[]).join('、')||(b.kind==='exile'?'未单列':'待核实'))}；有票权 ${esc(b.eligible_voters?.join('、')||'待核实')}；${status}</p><div class="table-scroll"><table><tr><th>投票者</th><th>投向</th></tr>${rows}</table></div></details>`;
    }).join('');
  }
  function phaseFindings(game,number,phase){
    return (game.review.phase_findings||[]).filter(f=>f.round===number&&f.phase===phase).map(f=>{
      const pending=f.status==='unresolved';
      const label=pending?'需你确认':f.status==='inferred'?'前后信息推断':f.status==='not_observed'?'资料未公开':f.confirmation_status==='user_confirmed'?'用户已确认':'已交叉核实';
      return `<details class="phase-finding ${pending?'question':''}" ${pending?'open':''}><summary><span class="tag ${pending?'pending':f.status==='not_observed'?'':'good'}">${label}</span>${esc(f.title)}</summary><p>${esc(f.conclusion||f.reasoning||'')}</p>${f.reasoning&&f.reasoning!==f.conclusion?`<p class="muted">${esc(f.reasoning)}</p>`:''}${evidence(f.evidence)}</details>`;
    }).join('');
  }
  function voteControl(game,number){
    const control=game.vote_control;if(!control?.applicable)return '';
    const row=control.phases.find(r=>r.round===number);if(!row)return '';
    const votes=n=>n==null?'待核实':esc(n)+'票';
    const badge=row.badge_known?(row.badge_holder?`${esc(row.badge_holder)}号持警徽`:'无警徽'):'警徽归属待核实';
    const verdict=row.controls_vote===true?'可用票权满足狼人方大于等于好人方的绑票条件':row.controls_vote===false?'本日理论票力尚不满足绑票条件':'本日可用票数仍待核实';
    const process=row.actual_ballot_exists?'本日实际逐人票型见上表。':row.exile_status==='interrupted_self_destruct'?'本日放逐因自爆中断，未举行放逐投票。':'本日没有已保存的放逐票轮，是否举行及前置流程见本日待核项或终局记录。';
    return `<div class="vote-control"><h4>狼混绑票核对</h4><p>${process}</p><p>${esc(row.werewolf_count??'待核')}名狼人阵营玩家（含狼混）：${esc(row.werewolf_seats?.join('、')||'待核实')}号；${esc(row.good_count??'待核')}名好人：${esc(row.good_seats?.join('、')||'待核实')}号。</p><p>${badge}；<b>可用票数（理论票力）：狼人阵营 ${votes(row.werewolf_votes)}，好人阵营 ${votes(row.good_votes)}</b>。</p><p>${verdict}。${row.badge_holder?'警长额外半票已计入持徽者阵营。':''}</p><details><summary>查看本次确认的绑票口径</summary><p>${esc(control.rule)}</p><p>${esc(control.winner_reason)}</p>${evidence(control.evidence)}</details></div>`;
  }
  function endgame(game){
    return (game.endgame?.phases||[]).map(p=>`<details open><summary><b>第${esc(p.day)}天 · 狼人拍刀</b> · ${p.result==='werewolf_win'?'拍刀成功，狼人获胜':p.result==='good_win'?'拍刀失败，好人获胜':'结果待核'}</summary><p>行动者：${p.actor?esc(p.actor)+'号':'未单独点名'}；明确目标：${esc(p.declared_targets.join('、'))}号（目标集合不表示刀序）</p><p>${esc(p.note)}</p>${evidence(p.evidence)}</details>`).join('');
  }
  function additional(game,day,phase){
    const separate=new Set(['wolf_shot','wolf_tap','wolf_pack_kill','sheriff_vote_pk','exile_vote_rerun']);
    return (game.supplemental_events||[]).filter(x=>x.round===day&&x.phase===phase&&!separate.has(x.event.slot)).map(x=>eventText(x.event)).join('');
  }
  function renderList(){
    const term=$('search').value.trim().toLowerCase(),filter=$('filter').value;
    const shown=data.games.filter(g=>{
      const b=g.entry.bvid,r=record(b),human=g.review.phase_review_counts?.unresolved||g.review.human_questions?.length||0;
      return (!term||JSON.stringify([g.entry.date,g.entry.board_name,b,g.dossier.seats]).toLowerCase().includes(term)) &&
        (filter==='all'||filter==='human'&&human>0||filter==='unpublished'&&(g.review.phase_review_counts?.not_observed||0)>0||filter==='unreviewed'&&r.status!=='accept'||filter==='accepted'&&r.status==='accept');
    });
    $('list').innerHTML=shown.map(g=>`<button class="game-link ${g.entry.bvid===current?'selected':''}" data-game="${esc(g.entry.bvid)}"><strong>${esc(g.entry.date)} 第${esc(g.entry.game_number)}局</strong>${esc(g.entry.board_name)}<br><span class="${g.review.phase_review_counts?.unresolved?'pending':'muted'}">${g.review.phase_review_counts?.unresolved||0} 项待核实${g.review.phase_review_counts?.not_observed?` · 资料未公开${g.review.phase_review_counts.not_observed}条`:''} · ${esc(stateLabels[record(g.entry.bvid).status]||'尚未确认')}</span></button>`).join('') || '<p class="muted">没有符合条件的对局。</p>';
    document.querySelectorAll('[data-game]').forEach(b=>b.onclick=()=>{current=b.dataset.game;renderList();renderGame();});
  }
  function renderGame(){
    const g=currentGame();if(!g){$('game').innerHTML='<p>尚无已完成AI逐局复核的候选。</p>';return;}
    const d=g.dossier,r=g.review,fb=record(current);
    const wolves=new Set(['狼人','机械狼','狼王','黑狼王','假面','诡术师','典狱长','盗宝大师','九尾狐','狼术师']);
    const groups=[['狼人侧',s=>wolves.has(s.role)||s.role==='混血儿'&&s.faction==='werewolf'],['神职',s=>s.role&&s.role!=='平民'&&s.role!=='混血儿'&&!wolves.has(s.role)],['平民与待核',s=>!s.role||s.role==='平民'||s.role==='混血儿'&&s.faction!=='werewolf']];
    const seatColumns=groups.map(([title,test])=>`<div><h4>${title}</h4>${d.seats.filter(test).map(s=>`<div class="seat"><strong>${esc(s.seat)}号 ${esc(s.name||'姓名待核')}</strong><div>${esc(s.role||'身份待核')} <span class="muted">${esc(faction[s.faction]||'阵营待核')}</span></div>${learningInfo(g,s)}</div>`).join('')}</div>`).join('');
    const questions=(r.human_questions||[]).map((q,i)=>{
      const id=q.id||String(i),saved=fb.questions?.[id]||{};
      return `<div class="question"><b>${i+1}. ${esc(q.phase_label||'阶段待定位')} · ${esc(q.question)}</b><p>${esc(q.reason||'')}</p><label>你的结论<select data-question="${esc(id)}"><option value="">尚未填写</option>${(q.options||[]).map(o=>`<option ${saved.answer===o?'selected':''}>${esc(o)}</option>`).join('')}<option value="custom" ${saved.answer==='custom'?'selected':''}>其他更正（请在下方说明）</option><option value="unsure" ${saved.answer==='unsure'?'selected':''}>仍不确定</option></select></label><textarea data-q-comment="${esc(id)}" placeholder="核对结果与依据">${esc(saved.comment||'')}</textarea>${evidence(q.evidence)}</div>`;
    }).join('');
    const days=new Set([...(d.rounds||[]).map(x=>x.number),...(g.voting.days||[]).map(x=>x.day),...(g.voting.ballots||[]).map(x=>x.day).filter(Number.isInteger),...(r.phase_findings||[]).map(x=>x.round).filter(Number.isInteger)]);
    const timeline=[...days].sort((a,b)=>a-b).map(n=>{
      const phasePending=(r.phase_findings||[]).some(f=>f.round===n&&f.status==='unresolved');
      if(g.flow?.terminal&&n>g.flow.terminal.round&&!phasePending)return '';
      const round=(g.presentation?.rounds||d.rounds||[]).find(x=>x.number===n)||{night:[],day:[]};
      const night=(round.night||[]).filter(e=>!['unavailable','none'].includes(e.action)||e.invalidated||e.blocked_by_game_end);
      const day=(round.day||[]).filter(e=>!['unavailable','none'].includes(e.action)||e.invalidated||e.blocked_by_game_end);
      const dayPhase=g.flow?.display_phases?.find(p=>p.round===n&&p.phase==='day');
      const showDay=!g.flow||Boolean(dayPhase);
      const visibleDay=dayPhase?.event_slots?day.filter(e=>dayPhase.event_slots.includes(e.slot)):day;
      const settlement=!showDay?day.filter(e=>e.slot==='night_deaths'&&e.action!=='unknown'||e.blocked_by_game_end).map(eventText).join(''):'';
      const nightFindings=phaseFindings(g,n,'night'),dayFindings=phaseFindings(g,n,'day');
      const nightPending=(r.phase_findings||[]).filter(f=>f.round===n&&f.phase==='night'&&f.status==='unresolved').length;
      const dayPending=(r.phase_findings||[]).filter(f=>f.round===n&&f.phase==='day'&&f.status==='unresolved').length;
      return `<section><div data-round="${n}" data-phase="night"><div class="phase-title">${n===1?'开局夜晚':`第${n-1}天夜晚`}${nightPending?` <span class="tag pending">${nightPending}项待核实</span>`:''}</div>${night.map(eventText).join('')||'<p class="muted">本轮夜间记录见下方原文及待核项。</p>'}${additional(g,n,'night')}${settlement}${nightFindings}${!showDay&&!dayPending?dayFindings:''}</div>${showDay||dayPending?`<div data-round="${n}" data-phase="day"><div class="phase-title">${esc(dayPhase?.label||`第${n}天白天`)}${dayPending?` <span class="tag pending">${dayPending}项待核实</span>`:''}</div>${showDay?visibleDay.map(eventText).join('')+additional(g,n,'day')+ballots(g,n)+voteControl(g,n):''}${dayFindings}</div>`:''}</section>`;
    }).join('');
    $('game').innerHTML=`<section class="card"><span class="tag" id="review-state">逐局候选 · ${esc(stateLabels[fb.status]||'用户尚未确认')}</span>${r.phase_review_counts?.unresolved?`<span class="tag pending">${r.phase_review_counts.unresolved}项需你核对，见对应日夜</span>`:'<span class="tag good">已完成逐日核对，无需你逐项复查</span>'}<h2>${esc(g.entry.date)} 第${esc(g.entry.game_number)}局 · ${esc(g.entry.board_name)}</h2><div class="actions"><button id="previous-game">上一局</button><button id="next-game">下一局</button></div><p class="muted">${esc(current)} · ${esc(g.entry.title)}</p><div class="facts"><span>胜方：<b>${esc(faction[d.winner]||'待核')}</b></span><span>解说：${esc((d.commentators||[]).join('、')||'待核')}</span><span>法官：${esc(d.referee||'待核')}</span></div><p>${link(g.video_url,'B站原视频')}　${link(g.source_url,'原始转写JSON')}　${link(g.dossier_url,'候选档案JSON')}</p><audio id="audio" controls preload="none" src="${esc(g.audio_url)}"></audio><p>${esc(r.summary||'')}</p></section>
    <section class="card"><h3>座位与实际底牌候选</h3><div class="seat-columns">${seatColumns}</div><details><summary>查看座位、身份与票型截图</summary><a href="${esc(g.frame_url)}" target="_blank" rel="noopener"><img class="frame" loading="lazy" src="${esc(g.frame_url)}" alt="本局座位身份与票型画面"></a><p class="muted">截图 ${time(g.entry.frame.frame_time_ms)}；画面自称、推测、选票数字与底牌标签分别核对。</p></details></section>
    <section class="card"><h3>逐夜、逐日事件与票型</h3><div class="timeline">${timeline||'<p>轮次待核。</p>'}</div>${endgame(g)}<h4>游戏结束</h4><p>${esc(faction[d.winner]||'胜方待核')}；拍刀、猎杀、技能结算见原文与推导依据。</p></section>
    <section class="card"><h3>悍跳推导</h3>${(r.bluffs||[]).map(b=>`<details open><summary>${esc(b.seat)}号 ${esc(d.seats.find(s=>s.seat===b.seat)?.name||'')} · ${b.attempted===true?'有悍跳尝试':b.attempted===false?'未见悍跳尝试':'尝试待核'} · ${b.success===true?'成功':b.success===false?'未成功':'成功与否待核'}</summary><p>第${esc(b.day||1)}天 · 所跳身份 ${esc(b.claimed_role||'待核')}</p><p>${esc(b.reasoning||'')}</p>${evidence(b.evidence)}</details>`).join('')||'<p class="muted">本轮未记录明确悍跳候选，不能据此自动统计为0次。</p>'}${(r.separate_identity_claims||[]).length?'<h4>另列的身份自称</h4>':''}${(r.separate_identity_claims||[]).map(b=>`<details open><summary>${esc(b.seat)}号 ${esc(d.seats.find(s=>s.seat===b.seat)?.name||'')} · ${esc(b.category_label)} · ${esc(b.counting_note)}</summary><p>第${esc(b.day||1)}天 · 自称 ${esc(b.claimed_role||'待核')}</p><p>${esc(b.reasoning||'')}</p>${evidence(b.evidence)}</details>`).join('')}</section>
    <section class="card"><h3>需要你亲自核对</h3>${questions||'<p>本局没有需要你亲自核对的遗留项。</p>'}</section>
    ${(r.phase_findings||[]).some(f=>f.status==='not_observed')?`<section class="card unpublished"><h3>资料未公开（保留未知）</h3><p class="muted">本局记录如下；<a href="S23_资料未公开清单.csv" target="_blank" rel="noopener">查看全部清单</a>。</p>${r.phase_findings.filter(f=>f.status==='not_observed').map(f=>`<details><summary>${esc(f.phase_label)} · ${esc(f.title)}</summary><p>${esc(f.conclusion)}</p><p class="muted">${esc(f.reasoning||'')}</p>${evidence(f.evidence)}</details>`).join('')}</section>`:''}
    ${(r.open_ai_followups||[]).length?`<section class="card question"><h3>留待后续的AI核对</h3><p>本局候选尚有以下收尾事项，本次先交付查看；这些事项会在后续继续核对。</p><ul>${r.open_ai_followups.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>`:''}
    <section class="card"><h3>AI更正与推导依据</h3>${r.daily_audit?`<details><summary>本轮逐日核对记录 · ${(r.daily_audit_changes||[]).length}项事件补正</summary><ul>${(r.daily_audit.checks||[]).map(x=>`<li>${esc(typeof x==='string'?x:JSON.stringify(x))}</li>`).join('')}</ul>${(r.daily_audit_changes||[]).map(x=>`<details><summary>第${x.round}轮 · ${esc(x.phase==='night'?'夜间':'白天')} · ${esc(data.slot_labels[x.slot]||x.slot)}</summary><p>原记录：${esc(JSON.stringify(x.before))}</p><p>本轮记录：${esc(JSON.stringify(x.after))}</p></details>`).join('')}</details>`:''}${(r.decisions||[]).map(x=>`<details><summary>${esc(x.field)} · ${esc(x.reasoning||'')}</summary><p><b>原候选：</b>${esc(typeof x.before==='object'?JSON.stringify(x.before):x.before)}</p><p><b>当前候选：</b>${esc(typeof x.after==='object'?JSON.stringify(x.after):x.after)}</p>${evidence(x.evidence)}</details>`).join('')||'<p class="muted">本局基线未作字段更改；身份与结果仍以本轮核对来源为准。</p>'}<details><summary>底牌核对依据</summary>${(r.role_evidence||[]).map(x=>`<p>${esc(x.reasoning||'')}</p>${evidence(x.evidence)}`).join('')}</details></section>
    <section class="card"><h3>最终复盘 · 带时间戳转写</h3><p class="muted">${g.recap_window?`${time(g.recap_window.start_ms)}—${time(g.recap_window.end_ms)}；${esc(g.recap_window.basis||'法官最终复盘')}`:'复盘窗口待定位'}。核对使用完整原始转写。</p><input id="cue-search" type="search" placeholder="在最终复盘中搜索"><div id="transcript" class="transcript"></div></section>
    <section class="card"><h3>本局复核意见</h3><div class="feedback"><label>本局结论<select id="game-status">${Object.entries(stateLabels).map(([k,v])=>`<option value="${k}" ${fb.status===k?'selected':''}>${v}</option>`).join('')}</select></label><label>更正或补充说明<textarea id="game-comment">${esc(fb.comment||'')}</textarea></label></div><p class="muted">确认只保存为本页意见，不会修改正式数据库。导出后交回再处理。</p></section>`;
    if((r.open_ai_followups||[]).length)$('review-state').insertAdjacentHTML('afterend','<span class="tag pending">AI核对尚有收尾</span>');
    const saveGame=()=>{
      const value={bvid:current,candidate_sha256:g.candidate_sha256,source_sha256:g.entry.source_sha256,status:$('game-status').value,comment:$('game-comment').value,questions:{},updated_at_utc:new Date().toISOString()};
      document.querySelectorAll('[data-question]').forEach(x=>{const id=x.dataset.question;const comment=[...document.querySelectorAll('[data-q-comment]')].find(c=>c.dataset.qComment===id)?.value||'';if(x.value||comment)value.questions[id]={answer:x.value,comment};});
      feedback.games[current]=value;$('review-state').textContent='逐局候选 · '+stateLabels[value.status];persist();renderList();
    };
    $('game-status').onchange=saveGame;$('game-comment').oninput=saveGame;
    const position=data.games.findIndex(x=>x.entry.bvid===current);
    $('previous-game').disabled=position<=0;$('next-game').disabled=position>=data.games.length-1;
    $('previous-game').onclick=()=>{current=data.games[position-1].entry.bvid;renderList();renderGame();window.scrollTo(0,0);};
    $('next-game').onclick=()=>{current=data.games[position+1].entry.bvid;renderList();renderGame();window.scrollTo(0,0);};
    document.querySelectorAll('[data-question],[data-q-comment]').forEach(x=>{x.oninput=saveGame;x.onchange=saveGame;});
    document.querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>seek(Number(b.dataset.seek)));
    $('cue-search').oninput=renderTranscript;renderTranscript();
  }
  function seek(ms){const audio=$('audio');if(!audio)return;audio.currentTime=ms/1000;audio.play().catch(()=>{$('status').textContent='请点击音频播放按钮，或打开B站视频定位。';});}
  function renderTranscript(){const g=currentGame();if(!g)return;const term=$('cue-search')?.value.trim()||'';const rows=(g.transcript||[]).filter(s=>!term||s.text.includes(term));$('transcript').innerHTML=rows.map(s=>`<div class="cue"><button data-cue-time="${s.start_ms}">${time(s.start_ms)}</button>${esc(s.text)}</div>`).join('');document.querySelectorAll('[data-cue-time]').forEach(b=>b.onclick=()=>seek(Number(b.dataset.cueTime)));}
  $('search').oninput=renderList;$('filter').onchange=renderList;
  $('reviewer').oninput=()=>{feedback.reviewer=$('reviewer').value;persist();};
  $('export').onclick=()=>{
    feedback.reviewer=$('reviewer').value;feedback.exported_at_utc=new Date().toISOString();
    const blob=new Blob([JSON.stringify(feedback,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='S23_逐局复核意见_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  $('import').onclick=()=>$('file').click();
  $('file').onchange=async()=>{
    const file=$('file').files[0];if(!file)return;
    try{
      const v=JSON.parse(await file.text());if(v.kind!=='S23_game_review_feedback_v1'||v.snapshot_id!==data.snapshot_id||!v.games||typeof v.games!=='object')throw new Error('文件类型或候选快照不匹配，请勿覆盖当前意见。');
      const merged={...feedback.games};for(const g of data.games){const x=v.games[g.entry.bvid];if(!x)continue;if(x.candidate_sha256!==g.candidate_sha256||x.source_sha256!==g.entry.source_sha256)throw new Error(g.entry.bvid+' 的源文件或候选版本不匹配');if(!Object.hasOwn(stateLabels,x.status))throw new Error('无效结论');merged[g.entry.bvid]={bvid:g.entry.bvid,candidate_sha256:g.candidate_sha256,source_sha256:g.entry.source_sha256,status:x.status,comment:String(x.comment||''),questions:x.questions&&typeof x.questions==='object'?x.questions:{},updated_at_utc:x.updated_at_utc};}
      feedback.games=merged;if(v.reviewer)feedback.reviewer=String(v.reviewer);$('reviewer').value=feedback.reviewer;persist();renderList();renderGame();
    }catch(e){$('status').textContent='导入未完成：'+e.message;}
    $('file').value='';
  };
  $('summary').textContent=`75局正赛 · 候选 ${data.games.length} 局 · ${data.summary.phase_pending_games||0} 局含待核事项（共 ${data.summary.phase_pending_items||0} 项，已标日夜）· 12局表演赛已排除`;
  $('footer').textContent='候选快照 '+data.snapshot_id+'；生成于 '+new Date(data.generated_at_utc).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+'（北京时间）。原始转写不改写，AI判断与用户确认分别保留。';
  renderList();renderGame();
})();
