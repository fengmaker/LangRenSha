/* Execute the same pure ranking/query functions used by the static browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const modules = path.resolve(process.argv[2]);
const source = path.resolve(process.argv[3]);
const ts = require(path.join(modules, 'typescript'));
function load(relative) {
  const code = ts.transpileModule(fs.readFileSync(path.join(source, relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(require, module, module.exports);
  return module.exports;
}
const { filterRankingEntries } = load('lib/ranking-filter.ts');
const entries = [
  { id: 'a', rank: 1, appearances: 2, sample_count: 9, effective_game_count: 1, value: 0.667 },
  { id: 'b', rank: 1, appearances: 10, sample_count: 10, effective_game_count: 3, value: 0.667 },
  { id: 'c', rank: 3, appearances: 10, sample_count: 10, effective_game_count: 5, value: 0.667 },
  { id: 'd', rank: 4, appearances: 10, sample_count: 10, effective_game_count: 6, value: 0.5 },
];
assert.deepEqual(filterRankingEntries(entries).map(x => [x.rank, x.tied]),
  [[1, true], [1, true], [3, false], [4, false]]);
assert.deepEqual(filterRankingEntries(entries, { minimumAppearances: 5 }).map(x => [x.id, x.rank, x.tied]),
  [['b', 1, false], ['c', 2, false], ['d', 3, false]]);
assert.deepEqual(filterRankingEntries(entries, { minimumAppearances: 5, minimumEffectiveGames: 4 }).map(x => [x.id, x.rank]),
  [['c', 1], ['d', 2]]);
assert.deepEqual(filterRankingEntries(entries, { minimumAppearances: 100 }), []);
assert.equal(entries[2].rank, 3);

const nestedMetricEntries = [
  { id: 'few-role-games', rank: 1, appearances: 1, sample_count: 8, effective_game_count: 4, value: 0.5 },
  { id: 'many-role-games-low-total', rank: 2, appearances: 6, sample_count: 8, effective_game_count: 4, value: 0.4 },
  { id: 'few-effective-games', rank: 3, appearances: 2, sample_count: 8, effective_game_count: 2, value: 0.3 },
];
const totalAppearancesByPlayer = new Map([
  ['few-role-games', 8], ['many-role-games-low-total', 2], ['few-effective-games', 7],
]);
assert.deepEqual(filterRankingEntries(nestedMetricEntries, {
  minimumAppearances: 5, totalAppearancesByPlayer,
}).map(x => [x.id, x.rank]), [['few-role-games', 1], ['few-effective-games', 2]]);
assert.deepEqual(filterRankingEntries(nestedMetricEntries, {
  minimumAppearances: 5, minimumEffectiveGames: 3, totalAppearancesByPlayer,
}).map(x => [x.id, x.rank]), [['few-role-games', 1]]);
assert.equal(nestedMetricEntries[0].appearances, 1);

const { filterAndSortGames, validateGameFilters } = load('lib/game-query.ts');
const game = (id, date, number, name) => ({ id, date, game_number: number, season: 'S23', phase: 'regular',
  board: { code: 'board', name: '版型' }, players: [{ id: 'p', name }], search_text: `${id} BVx 版型 ${name}` });
const games = [game('z', '2026-11-01', null, '选手'), game('b', '2026-11-01', 2, '选手'),
  game('a', '2026-11-01', 2, '选手'), game('y', '2026-11-02', 1, '其他')];
assert.deepEqual(filterAndSortGames(games, {}).map(x => x.id), ['y', 'a', 'b', 'z']);
assert.deepEqual(filterAndSortGames(games, { player: '选手', q: 'bVx', date_from: '2026-11-01', date_to: '2026-11-01' }).map(x => x.id), ['a', 'b', 'z']);
assert.equal(filterAndSortGames(games, { player: 'p' }).length, 4);
assert.equal(filterAndSortGames(games, { player: ' 选手' }).length, 0);
assert.equal(validateGameFilters({ date_from: '2024-02-29', date_to: '2024-03-01' }), null);
assert.match(validateGameFilters({ date_from: '2026-02-30' }), /开始日期/);
assert.match(validateGameFilters({ date_to: '2026-2-03' }), /截止日期/);
assert.match(validateGameFilters({ date_from: '2026-03-02', date_to: '2026-03-01' }), /不能晚于/);
assert.match(validateGameFilters({ q: 'x'.repeat(121) }), /关键词筛选最多120/);
assert.match(validateGameFilters({ player: '选'.repeat(121) }), /选手筛选最多120/);
assert.match(validateGameFilters({ season: 'S'.repeat(33) }), /赛季筛选最多32/);
assert.match(validateGameFilters({ phase: 'x'.repeat(33) }), /比赛阶段筛选最多32/);
assert.match(validateGameFilters({ board: 'x'.repeat(65) }), /版型筛选最多64/);
assert.match(validateGameFilters({ date_from: '' }), /开始日期/);
assert.deepEqual(filterAndSortGames(games, { date_from: '2026-02-30' }), []);
console.log('Static ranking ties, combined thresholds, filtering and stable ordering passed');
