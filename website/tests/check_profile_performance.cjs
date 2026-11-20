/* Offline SSR checks for new player profile performance metrics. */
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
      learningDistribution: 'learningDistribution', chapterNav: 'chapterNav',
      distribution: 'distribution', winTable: 'winTable', rateTrack: 'rateTrack',
      boardRecord: 'boardRecord', narrowRecord: 'narrowRecord',
    };
    if (name === './season-range-filter') return { SeasonRangeFilter: () => null };
    if (name === '@/components/archive-link') return {
      ArchiveLink: ({ href, children, ...props }) => React.createElement('a', { ...props, href }, children),
    };
    if (name === '@/components/static-player-photo') return { StaticPlayerPhoto: () => null };
    if (name === '@/lib/site-mode') return { publicPagePath: (value) => value };
    if (name === '@/lib/format') return load('lib/format.ts');
    if (name === '@/lib/ranking-filter') return load('lib/ranking-filter.ts');
    if (name === '@/components/metric-samples') return load('components/metric-samples.tsx');
    if (name === './metric-rank') return load('app/players/[id]/metric-rank.tsx');
    if (name === './player-chapters') return load('app/players/[id]/player-chapters.tsx');
    if (name === './player-win-distributions') return load('app/players/[id]/player-win-distributions.tsx');
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

function profile({ roles = [{ role: '女巫', appearances: 1, wins: 0, losses: 1, pending_games: 0, win_rate: 0 }], performance = {}, ledger = [] } = {}) {
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
    performance, roles, boards: [], ledger, notes: [], rankings: {}, ranking_boards: {},
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
    first_night_death: metric({ numerator: 1, denominator: 2, samples: [] }),
    first_day_exiled: metric({ numerator: 0, denominator: 2, samples: [] }),
  },
});
witch.stats.rankings.witch_poison_count = { rank: 1, total: 1, tied: false };
witch.stats.ranking_boards.witch_poison_count = [{ id: 'p1', name: '甲', rank: 1, tied: false, value: 0, sample_count: 0, appearances: 1 }];
witch.stats.rankings.first_night_targeted = null;
for (const key of ['first_night_death', 'first_day_exiled']) {
  witch.stats.rankings[key] = { rank: 1, total: 1, tied: false };
  witch.stats.ranking_boards[key] = [{ id: 'p1', name: '甲', rank: 1, tied: false,
    value: witch.stats.performance[key].numerator, sample_count: 2, appearances: 1 }];
}
witch.stats.boards = [
  { code: 'small', name: '少出场版型', appearances: 1, wins: 1, losses: 0, win_rate: 1, metric: metric() },
  { code: 'large', name: '多出场版型', appearances: 2, wins: 0, losses: 1, pending_games: 1, win_rate: 0, metric: metric() },
];

const markup = render(witch);
const sectionOrder = ['好人表现', '神职表现', '狼人表现', '受袭与出局', '身份胜率分布'].map((label) => markup.indexOf(`<h2>${label}</h2>`));
assert(sectionOrder.every((index) => index >= 0));
assert.deepEqual(sectionOrder, [...sectionOrder].sort((a, b) => a - b));
assert.match(markup, /aria-label="选手档案章节"/);
for (const id of ['overview', 'good', 'divine', 'wolf', 'lifecycle', 'roles', 'boards', 'games']) {
  assert.match(markup, new RegExp(`href="#profile-${id}"`));
  assert.match(markup, new RegExp(`id="profile-${id}"`));
}
assert.match(markup, /aria-sort="descending"[^>]*><button[^>]*>出场/);
assert(markup.indexOf('data-board-code="large"') < markup.indexOf('data-board-code="small"'));
assert.match(markup, /1 场待结算/);
assert.match(markup, /<table class="distribution winTable" aria-label="身份胜率分布"/);
assert.match(markup, /<th scope="col">身份<\/th><th scope="col">胜率<\/th><th scope="col">排名<\/th><th scope="col">样本<\/th>/);
assert.match(markup, /aria-label="神职身份"/);
assert.match(markup, /aria-pressed="true">女巫·毒师<\/button>/);
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
assert.match(lifecycleCard, /暂无排名/);
assert.match(cardFor(markup, '首夜死亡次数'), /aria-label="首夜死亡次数：查看排行榜"/);
assert.match(cardFor(markup, '首日被放逐次数'), /aria-label="首日被放逐次数：查看排行榜"/);
for (const label of ['女巫施毒次数', '女巫毒狼率', '女巫毒杀狼人次数', '首夜狼刀目标次数']) {
  assert.doesNotMatch(cardFor(markup, label), /<small>/, `${label} should not show inline numerator/denominator copy`);
}

const hunterMarkup = render(profile({
  roles: [{ role: '猎人', appearances: 1, wins: 0, losses: 1, pending_games: 0, win_rate: 0 }],
  performance: { hunter_shot_count: metric({ numerator: 1, denominator: 1, samples: [] }) },
}));
assert.match(hunterMarkup, /aria-pressed="true">猎人<\/button>/);
assert.match(hunterMarkup, /猎人开枪次数/);

const poisonerMarkup = render(profile({
  roles: [{ role: '毒师', appearances: 1 }],
  performance: { witch_poison_count: metric({ numerator: 1, denominator: 1 }) },
}));
assert.match(poisonerMarkup, /aria-pressed="true">女巫·毒师<\/button>/);
assert.match(poisonerMarkup, /女巫施毒次数/);

const guardMarkup = render(profile({
  roles: [{ role: '守卫', appearances: 1 }],
  performance: { guard_count: metric(), guard_knife_hit_rate: metric({ rate: 0.5 }) },
}));
assert.match(guardMarkup, /aria-pressed="true">守卫<\/button>/);
assert.match(cardFor(guardMarkup, '守中狼刀率'), /<strong>50\.0%<\/strong>/);

const mechanicalRoles = [{ role: '机械狼', appearances: 1 }];
const guardGame = { game_id: 'g1', season: 'S23', date: '2026-11-01', board_name: '机械狼通灵师',
  role: '机械狼', mechanical_learned_role: '机械守卫', result: 'win', cumulative_points: 1.5 };
const mechanicalGuardMarkup = render(profile({
  roles: mechanicalRoles,
  ledger: [guardGame, { ...guardGame, game_id: 'g2', mechanical_learned_role: '机械平民' }],
  performance: {
    mechanical_learn_rate: metric({ numerator: 1, denominator: 2, rate: 0.5,
      game_ids: ['g1', 'g2'], samples: [
        { game_id: 'g1', positive: 1, negative: 0 }, { game_id: 'g2', positive: 0, negative: 1 },
      ] }),
    mechanical_reflect_god_kills: metric({ numerator: 1, denominator: 1 }),
  },
}));
const learningCard = cardFor(mechanicalGuardMarkup, '机械狼学身份率');
assert.match(learningCard, /aria-label="机械狼学身份率：查看分布"/);
assert.match(learningCard, /<th scope="row">守卫<\/th><td>1<\/td><td>50\.0%<\/td>/);
assert.match(learningCard, /<th scope="row">平民<\/th><td>1<\/td><td>50\.0%<\/td>/);
assert.match(learningCard, /<th scope="row">双刀<\/th><td>0<\/td><td>0\.0%<\/td>/);
assert.match(learningCard, /href="\/games\/g1"/);
assert.match(mechanicalGuardMarkup, /机械狼技能使用/);
assert.doesNotMatch(mechanicalGuardMarkup, /<button[^>]+>平民<\/button>/);
assert.match(cardFor(mechanicalGuardMarkup, '机械狼弹毒神次数'), /<strong>1<\/strong>/);

const ordinaryWolfMarkup = render(profile({
  roles: [{ role: '狼人', appearances: 1 }],
  performance: { mechanical_wolf_count: metric(), mechanical_wolf_rate: metric({ denominator: 1, rate: 0 }) },
}));
assert.match(ordinaryWolfMarkup, /机械狼学习技能/);
assert.match(cardFor(ordinaryWolfMarkup, '机械狼次数'), /<strong>0<\/strong>/);
assert.match(cardFor(ordinaryWolfMarkup, '机械狼率'), /<strong>0\.0%<\/strong>/);
assert.doesNotMatch(ordinaryWolfMarkup, /机械狼学身份率|机械狼技能使用/);

const factionMarkup = render(profile({
  roles: ['狼人', '平民', '混血儿'].map((role, index) => ({
    role, appearances: 3 - index, wins: 1, losses: 1, pending_games: 0, win_rate: 0.5,
  })),
  ledger: [
    ['狼人', 'werewolf'], ['平民', 'good'], ['混血儿', 'good'],
  ].map(([role, faction], index) => ({ ...guardGame, game_id: `faction-${index}`, role, faction })),
}));
const factionRows = [...factionMarkup.matchAll(/<tr data-profile-tone="(good|wolf|other)"><th scope="row">([^<]+)<\/th>/g)];
assert.deepEqual(factionRows.map(([, group, role]) => [group, role]), [
  ['good', '平民'], ['other', '混血儿'], ['wolf', '狼人'],
]);
assert.doesNotMatch(factionMarkup, /<h3>(好人阵营|狼人阵营|其他／待核阵营)<\/h3>/);

for (const [key, label] of [
  ['mechanical_poison_god_kills', '机械狼毒神次数'],
  ['mechanical_shot_god_kills', '机械狼枪神次数'],
  ['mechanical_check_count', '机械狼查验次数'],
  ['mechanical_extra_attack_count', '机械狼技能刀次数'],
]) {
  const skillMarkup = render(profile({ roles: mechanicalRoles,
    performance: { [key]: metric({ numerator: 1, denominator: 1 }) } }));
  assert.match(cardFor(skillMarkup, label), /<strong>1<\/strong>/);
  assert.doesNotMatch(skillMarkup, /机械狼(?:毒狼率|枪狼率|毒杀狼人次数|击杀狼人次数)/);
}

console.log('Player profile performance SSR checks passed');
