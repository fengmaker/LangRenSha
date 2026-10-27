/* Offline SSR checks for the actual timeline and ballot React components. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [modulesArg, sourceArg] = process.argv.slice(2);
if (!sourceArg) throw Error('Usage: node check_web_semantics.cjs NODE_MODULES WEB_SRC');
const modules = path.resolve(modulesArg);
const source = path.resolve(sourceArg);
const ts = require(path.join(modules, 'typescript'));
const React = require(path.join(modules, 'react'));
const { renderToStaticMarkup } = require(path.join(modules, 'react-dom/server'));
const cache = {};

function load(relative) {
  const filename = path.join(source, relative);
  if (cache[filename]) return cache[filename].exports;
  const module = { exports: {} };
  cache[filename] = module;
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const localRequire = name => {
    if (name === '@/lib/format') return load('lib/format.ts');
    if (name === '@/components/ballot-panel') return load('components/ballot-panel.tsx');
    return require(path.join(modules, name));
  };
  new vm.Script(`(function(require,module,exports){${code}\n})`, { filename })
    .runInThisContext()(localRequire, module, module.exports);
  return module.exports;
}

const { EventBoard } = load('components/event-board.tsx');
const seats = [
  { seat: 2, name: '甲', role: '狼人' }, { seat: 4, name: '乙', role: '猎人' },
  { seat: 8, name: '丙', role: '猎人' }, { seat: 10, name: '丁', role: '平民' },
];
function render({ rounds = [], voting = {}, terminal = null }) {
  return renderToStaticMarkup(React.createElement(EventBoard, { rounds, voting, seats, terminal }));
}

const badge = render({
  rounds: [{ number: 1, night: [], day: [{ slot: 'badge', action: 'badge_lost',
    result: '全员上警，警徽流失', description: '警徽流失，本局不再进行警长竞选。' }] }],
  voting: { days: [{ day: 1, sheriff: 'badge_lost' }] },
});
assert.match(badge, /警徽流失，本局不再进行警长竞选/);
assert.doesNotMatch(badge, /延期警长竞选再次被狼人自爆中断/);

const revote = render({
  rounds: [],
  voting: { ballots: [{ id: 'revote-1', day: 1, kind: 'exile', number: 2, stage: 'revote',
    status: 'complete', candidates: [2, 10], eligible_voters: [2, 4], votes: [], tied_candidates: [],
    winner: 2, unrecorded_voters: [] }] },
});
assert.match(revote, /技能重投/);
assert.doesNotMatch(revote, /其他投票轮次/);

const conflict = render({
  rounds: [{ number: 1, night: [], day: [{ slot: 'exile_result', action: 'exile', targets: [10] }] }],
  voting: { ballots: [{ id: 'conflict-1', day: 1, kind: 'exile', number: 1, stage: 'initial',
    status: 'complete', candidates: [2, 10], eligible_voters: [2, 4], votes: [], tied_candidates: [],
    winner: 2, unrecorded_voters: [] }] },
});
assert.match(conflict, /本轮结果与放逐事件记录冲突，待核实/);
assert.doesNotMatch(conflict, /本轮结果：2号/);
assert.match(conflict, /10号.*被放逐出局/);

const dq = render({ rounds: [{ number: 2, night: [], day: [{ slot: 'disqualification',
  action: 'disqualify', targets: [8], description: '8号玩家被DQ出局；此裁定与普通死亡结算分开记录。' }] }] });
assert.match(dq, /8号玩家被DQ出局/);
assert.match(dq, /DQ出局/);

const terminal = render({ terminal: { round: 4, phase: 'night', events: [{
  slot: 'night_deaths', action: 'die', targets: [4], terminal: true,
}] } });
assert.match(terminal, /data-phase="terminal"/);
assert.match(terminal, /本夜终局出局：4号乙（猎人）/);
assert.doesNotMatch(terminal, /天亮，昨夜出局/);

console.log('5 actual component SSR assertions passed');
