/* Read-only actual React component SSR. No server, browser, network, or source edits. */
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const [repoArg, modulesArg, inputArg, outputArg] = process.argv.slice(2);
if (!outputArg) throw Error('Usage: node check_render.cjs REPO NODE_MODULES INPUT_JSON OUTPUT_JSON');
const repo=path.resolve(repoArg), modules=path.resolve(modulesArg);
const ts=require(path.join(modules,'typescript')), React=require(path.join(modules,'react'));
const {renderToStaticMarkup}=require(path.join(modules,'react-dom/server'));
const cache={};
function load(relative) {
 const filename=path.join(repo,'website/web/src',relative);
 if(cache[filename]) return cache[filename].exports;
 const module={exports:{}};cache[filename]=module;
 const src=fs.readFileSync(filename,'utf8');
 const code=ts.transpileModule(src,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const localRequire=(name)=>{
  if(name==='@/lib/format')return load('lib/format.ts');
  if(name==='@/components/ballot-panel')return load('components/ballot-panel.tsx');
  return require(path.join(modules,name));
 };
 new vm.Script(`(function(require,module,exports){${code}\n})`,{filename}).runInThisContext()(localRequire,module,module.exports);
 return module.exports;
}
const {EventBoard}=load('components/event-board.tsx');
const games=JSON.parse(fs.readFileSync(inputArg,'utf8'));
const output=games.map(g=>{
 const html=renderToStaticMarkup(React.createElement(EventBoard,{rounds:g.presentation.rounds,voting:g.voting,seats:g.seats}));
 const plain=html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
 function around(term){const i=plain.indexOf(term);return i<0?null:plain.slice(Math.max(0,i-75),i+term.length+125);}
 return {game_id:g.id,bvid:g.source.bvid,day_sections:[...html.matchAll(/data-phase="day" data-day="(\d+)"/g)].map(x=>Number(x[1])),
  wrong_lost_badge:around('延期警长竞选再次被狼人自爆中断'),other_ballot_stage_count:(plain.match(/其他投票轮次/g)||[]).length,
  pending_hunter:around('档案确认猎人本日出局且具备开枪资格'),puppet_hunter_pending:around('猎人本日出局，开枪资格或开枪目标仍待核'),half_vote_explanation:around('警徽计票后报6号6.5票'),
  terminal_absence_note:around('D3未开始'),all_hunter_labels:[...plain.matchAll(/\d+号[^。]{0,50}本夜可开枪。/g)].map(x=>x[0])};
});
fs.writeFileSync(outputArg,JSON.stringify({scope:'Actual TSX components transpiled and React SSR rendered offline; no browser/live site checked',games:output},null,2)+'\n');
console.log(`Rendered ${output.length} game timelines from actual components`);
