/* Offline SSR checks for new player profile performance metrics. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [modulesArg, sourceArg] = process.argv.slice(2);
if (!sourceArg) throw Error('Usage: node check_profile_performance.cjs NODE_MODULES WEB_SRC');
const modules = path.resolve(modulesArg);
const source = path.resolve(sourceArg);
const ts = require(path.join(modules, 'typescript'));
const React = require(path.join(modules, 'react'));
const { renderToStaticMarkup } = require(path.join(modules, 'react-dom/server'));
const cache = new Map();

function load(relative) {
  const filename = path.join(source, relative);
  if (cache.has(filename)) return cache.get(filename).exports;
  const module = { exports: {} };
  cache.set(filename, module);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
  }).outputText;
  const localRequire = (name) => {
    if (name === 'react') return React;
    if (name === './player-detail.module.css') return {
      profile: 'profile', performanceTabs: 'performanceTabs', performanceTab: 'performanceTab',
      performancePanel: 'performancePanel', performanceSubsection: 'performanceSubsection',
    };
    if (name === './season-range-filter') return { SeasonRangeFilter: () => null };
    if (name === '@/components/archive-link') return {
      ArchiveLink: ({ href, children, ...props }) => React.createElement('a', { ...props, href }, children),
    };
    if (name === '@/components/static-player-photo') return { StaticPlayerPhoto: () => null };
    if (name === '@/lib/site-mode') return { isStaticSite: false, publicPath: (value) => value };
    if (name === '@/lib/format') return load('lib/format.ts');
    if (name === '@/lib/ranking-filter') return load('lib/ranking-filter.ts');
    if (name === '@/components/metric-samples') return load('components/metric-samples.tsx');
    if (name === './metric-rank') return load('app/players/[id]/metric-rank.tsx');
    if (name === 'react-dom') return require(path.join(modules, name));
    if (name.startsWith('react/')) return require(path.join(modules, name));
    throw new Error(`Unexpected import: ${name}`);
  };
  new vm.Script(`(function(require,module,exports){${code}\n})`, { filename })
    .runInThisContext()(localRequire, module, module.exports);
  return module.exports;
}

const { PlayerProfileView } = load('app/players/[id]/player-profile-view.tsx');

function metric(overrides = {}) {
  return { numerator: 0, denominator: 0, rate: null, excluded: 0, game_ids: [], samples: [], ...overrides };
}

function profile({ roles = [{ role: '女巫', appearances: 1, wins: 0, losses: 1, pending_games: 0, win_rate: 0 }], performance = {} } = {}) {
  const empty = metric();
  const stats = {
    appearances: 1, scope_games: 1, wins: 0, losses: 1, pending_games: 0, points: 0, points_complete: true,
    attendance: metric({ numerator: 1, denominator: 1, rate: 1 }),
    total_win_rate: metric({ numerator: 0, denominator: 1, rate: 0 }),
    werewolf_win_rate: empty, good_win_rate: metric({ numerator: 0, denominator: 1, rate: 0 }),
    sheriff_registration_rate: empty, wolf_vote_rate: empty, exile_abstentions: 0,
    good_sheriff_registration_rate: empty, good_off_police_rate: empty, werewolf_appearances: 0,
    werewolf_draw_rate: empty, werewolf_self_explosion_rate: empty, werewolf_sheriff_registration_rate: empty,
    werewolf_off_police_rate: empty, seer_follow_rate: empty, sheriff_seer_vote_rate: empty,
    bluff_count: 0, bluff_count_complete: true, bluff_pending_games: 0, bluff_rate: empty, bluff_success_rate: empty,
    performance, roles, boards: [], ledger: [], notes: [], rankings: {}, ranking_boards: {},
  };
  return {
    id: 'p1', name: '甲', appearances: 1, roles: roles.map(({ role }) => ({ role, count: 1 })), boards: [], games: [],
    release_id: 'release-1', stats, scope: { season: 'S23', phase: 'all', games: 1 }, available_seasons: ['S23'],
  };
}

function render(player) {
  return renderToStaticMarkup(React.createElement(PlayerProfileView, {
    player, start: 'S23', end: 'latest', minimumAppearances: 0,
  }));
}

function cardFor(markup, label) {
  const labelPosition = markup.indexOf(`<span>${label}</span>`);
  assert.notEqual(labelPosition, -1, `missing card ${label}`);
  const start = markup.lastIndexOf('<article class="profile-stat-card"', labelPosition);
  const end = markup.indexOf('</article>', labelPosition);
  assert(start >= 0 && end >= 0, `could not isolate card ${label}`);
  return markup.slice(start, end + '</article>'.length);
}

const witch = profile({
  performance: {
    witch_poison_count: metric({ numerator: 0, denominator: 0, samples: [] }),
    witch_poison_wolf_rate: metric({ numerator: 1, denominator: 2, rate: 0.5, samples: [] }),
    witch_poison_wolf_kills: metric({ numerator: 2, denominator: 2, excluded: 1, samples: [] }),
    first_night_targeted: metric({ numerator: 0, denominator: 2, excluded: 1, samples: [] }),
  },
});
witch.stats.rankings.witch_poison_count = { rank: 1, total: 1, tied: false };
witch.stats.ranking_boards.witch_poison_count = [{ id: 'p1', name: '甲', rank: 1, tied: false, value: 0, sample_count: 0, appearances: 1 }];

const markup = render(witch);
const sectionOrder = ['好人表现', '神职表现', '狼人表现', '受袭与出局', '身份胜率分布'].map((label) => markup.indexOf(label));
assert(sectionOrder.every((index) => index >= 0));
assert.deepEqual(sectionOrder, [...sectionOrder].sort((a, b) => a - b));
assert.match(markup, /aria-label="神职身份"/);
assert.match(markup, /aria-pressed="true">女巫<\/button>/);
assert.match(markup, /aria-pressed="false">猎人<\/button>/);
assert.match(markup, /aria-pressed="false">预言家·通灵师<\/button>/);
assert.match(cardFor(markup, '女巫施毒次数'), /<strong>0<\/strong>/);
assert.match(cardFor(markup, '女巫毒狼率'), /<strong>50\.0%<\/strong>/);
assert.match(cardFor(markup, '女巫毒杀狼人次数'), /<strong>≥2<\/strong>/);
assert.match(cardFor(markup, '女巫施毒次数'), /class="metric-rank"/);
assert.match(cardFor(markup, '女巫施毒次数'), /class="sample-trigger"/);
const lifecycleCard = cardFor(markup, '首夜狼刀目标次数');
assert.match(lifecycleCard, /<strong>—<\/strong>/);
assert.match(lifecycleCard, /class="sample-trigger"/);
assert.doesNotMatch(lifecycleCard, /ranking-control|metric-rank/);
for (const label of ['女巫施毒次数', '女巫毒狼率', '女巫毒杀狼人次数', '首夜狼刀目标次数']) {
  assert.doesNotMatch(cardFor(markup, label), /<small>/, `${label} should not show inline numerator/denominator copy`);
}

const hunterMarkup = render(profile({
  roles: [{ role: '猎人', appearances: 1, wins: 0, losses: 1, pending_games: 0, win_rate: 0 }],
  performance: { hunter_shot_count: metric({ numerator: 1, denominator: 1, samples: [] }) },
}));
assert.match(hunterMarkup, /aria-pressed="true">猎人<\/button>/);
assert.match(hunterMarkup, /猎人开枪次数/);

console.log('Player profile performance SSR checks passed');
