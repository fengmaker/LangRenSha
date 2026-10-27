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
const {BallotPanel}=load('components/ballot-panel.tsx');
const games=JSON.parse(fs.readFileSync(inputArg,'utf8'));
const output=games.map(g=>{
 const ballots=g.voting.ballots.map(b=>{
  const html=renderToStaticMarkup(React.createElement(BallotPanel,{voting:{ballots:[b]},seats:g.seats}));
  const plain=html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
  return {ballot_id:b.id,day:b.day,kind:b.kind,winner:b.winner,plain,default_marker_count:(plain.match(/默认弃票|规则默认/g)||[]).length};
 });
 return {game_id:g.id,bvid:g.source.bvid,ballots};
});
fs.writeFileSync(outputArg,JSON.stringify({scope:'Actual BallotPanel TSX offline React SSR; no browser/live site checked',games:output},null,2)+'\n');
console.log(`Rendered ${output.length} games' ballot panels from actual components`);
