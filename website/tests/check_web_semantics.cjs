/* Offline SSR checks for the actual timeline and ballot React components. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [modulesArg, sourceArg] = process.argv.slice(2);
const modules = path.resolve(modulesArg ?? path.join(__dirname, '../web/node_modules'));
const source = path.resolve(sourceArg ?? path.join(__dirname, '../web/src'));
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
const { gamePhaseLabel } = load('lib/format.ts');
function render(...phases) {
  return renderToStaticMarkup(React.createElement(EventBoard, { timeline: { phases }, seats }));
}

function phase(number, phaseName, items, terminal = false) {
  return { number, phase: phaseName, label: gamePhaseLabel(number, phaseName), terminal, items };
}

function eventItem(slot, action, title, text, details = {}) {
  return { kind: 'event', slot, title, text, events: [{ slot, action, ...details }] };
}

function exileBallot(id, stage, number) {
  return {
    kind: 'ballot', slot: 'exile_vote', title: '放逐投票',
    ballot: { id, day: 1, kind: 'exile', stage, number, status: 'complete',
      candidates: [2, 10], eligible_voters: [2, 4], votes: [], tied_candidates: [],
      winner: 2, unrecorded_voters: [] },
  };
}

const badge = render(phase(1, 'day', [
  eventItem('sheriff_result', 'badge_lost', '警长结果', '警徽流失，本局不再进行警长竞选。'),
]));
assert.match(badge, /警徽流失，本局不再进行警长竞选/);
assert.doesNotMatch(badge, /延期警长竞选再次被狼人自爆中断/);

const revote = render(phase(1, 'day', [exileBallot('revote-1', 'revote', 2)]));
assert.match(revote, /技能重投/);
assert.doesNotMatch(revote, /其他投票轮次/);

const conflict = render(phase(1, 'day', [
  exileBallot('conflict-1', 'initial', 1),
  eventItem('exile_result', 'exile', '放逐结果', '10号丁（平民）被放逐出局。', { targets: [10] }),
]));
assert.match(conflict, /本轮结果与放逐事件记录冲突，待核实/);
assert.doesNotMatch(conflict, /本轮结果：2号/);
assert.match(conflict, /10号.*被放逐出局/);

const dq = render(phase(2, 'day', [
  eventItem('disqualification', 'disqualify', 'DQ出局', '8号玩家被DQ出局。', { targets: [8] }),
]));
assert.match(dq, /data-slot="disqualification" data-action="disqualify"/);
assert.match(dq, /8号玩家被DQ出局/);

const localized = render(phase(1, 'night', [
  eventItem('wolf_attack', 'attack', '狼队击杀', '狼队选择10号丁（平民）。', { slot_label: 'wolf attack' }),
  eventItem('night_deaths', 'unknown', '夜间出局', '夜间出局情况待核。', { slot_label: 'night deaths' }),
  eventItem('witch_poison', 'poison', '毒师毒药', '毒师选择2号甲（狼人）。'),
]), phase(1, 'day', [
  eventItem('sheriff_candidates', 'register', '警长竞选', '登记上警。', { slot_label: 'sheriff candidates' }),
  exileBallot('localized-1', 'initial', 1),
]));
assert.doesNotMatch(localized, /wolf attack|night deaths|sheriff candidates|exile vote/);
assert.match(localized, /狼队击杀/);
assert.match(localized, /夜间出局情况待核/);
assert.match(localized, /毒师毒药/);
assert.match(localized, /登记上警/);
assert.match(localized, /放逐投票/);

const terminal = render(phase(3, 'day', [
  eventItem('exile_result', 'exile', '放逐结果', '10号丁（平民）被放逐出局。', { targets: [10] }),
]),
  phase(4, 'night', [
    eventItem('night_deaths', 'die', '夜间出局', '4号乙（猎人）出局。', { targets: [4], terminal: true }),
  ], true));
assert.match(terminal, /timeline-night timeline-terminal" data-phase="night" data-day="4"/);
assert.match(terminal, /终局结算/);
assert.match(terminal, /4号乙（猎人）出局/);
assert.doesNotMatch(terminal, /天亮，昨夜出局|data-phase="day" data-day="4"|data-day="5"/);

console.log('Timeline and ballot SSR checks passed');
