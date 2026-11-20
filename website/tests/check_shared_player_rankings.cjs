const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const [modulesArg, sourceArg] = process.argv.slice(2);
const modules = path.resolve(modulesArg ?? path.join(__dirname, '../web/node_modules'));
const source = path.resolve(sourceArg ?? path.join(__dirname, '../web/src'));
const ts = require(path.join(modules, 'typescript'));

function runtime() {
  const cache = new Map();
  function load(relative) {
    const filename = path.join(source, relative);
    const key = path.resolve(filename);
    if (cache.has(key)) return cache.get(key).exports;
    const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText;
    const module = { exports: {} };
    cache.set(key, module);
    const resolve = (name) => {
      if (name === '@/lib/site-mode') return { basePath: '/langrensha-site' };
      if (name === '@/lib/api-error') return load('lib/api-error.ts');
      if (name === '@/lib/player-rankings') return load('lib/player-rankings.ts');
      throw new Error(`Unexpected import: ${name}`);
    };
    new Function('require', 'module', 'exports', code)(resolve, module, module.exports);
    return module.exports;
  }
  return { load };
}

function manifest(schemaVersion = 2) {
  return { schema_version: schemaVersion, snapshot_id: 'snapshot-1', seasons: [{ id: 'S22' }],
    release_id: 'release-1', ranges: [] };
}

function scope(overrides = {}) {
  return { season_start: 'S22', season_end: 'S23', minimum_appearances: 3,
    seasons: ['S22', 'S23'], ...overrides };
}

function profile(id, overrides = {}) {
  return { id, release_id: 'release-1', analytics_version: 4, scope: scope(),
    stats: { games: 8, win_rate: 0.5 }, ...overrides };
}

function sharedRankings(overrides = {}) {
  return { release_id: 'release-1', analytics_version: 4, scope: scope(),
    ranking_boards: { overall: [{ player_id: 'p1', rank: 1 }] }, ...overrides };
}

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function withFetch(fetchImpl, run) {
  const previous = global.fetch;
  global.fetch = fetchImpl;
  return Promise.resolve().then(run).finally(() => { global.fetch = previous; });
}

function browserFixture({ schemaVersion = 2, profiles, shared = sharedRankings(), onRequest } = {}) {
  const requests = [];
  const fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    if (onRequest) return onRequest(String(url), requests.length);
    if (String(url).endsWith('/data/manifest.json')) return response(200, manifest(schemaVersion));
    const pathName = String(url);
    const player = pathName.match(/\/players\/([^/]+)\/[^/]+\.json$/)?.[1];
    if (player) return response(200, profiles[player]);
    if (pathName.includes('/rankings/')) return response(200, shared);
    throw new Error(`Unexpected static request: ${pathName}`);
  };
  return { browser: runtime().load('lib/static-browser.ts'), requests, fetch };
}

async function testClientMergesSharedRankingsWithoutMutatingProfile() {
  const sourceProfile = profile('p1');
  const original = structuredClone(sourceProfile);
  const { browser, fetch } = browserFixture({ profiles: { p1: sourceProfile } });
  const result = await withFetch(fetch, () => browser.fetchPlayerRange('p1', 'S22', 'S23'));

  assert.deepEqual(result.stats.ranking_boards, sharedRankings().ranking_boards);
  assert.notEqual(result, sourceProfile);
  assert.notEqual(result.stats, sourceProfile.stats);
  assert.deepEqual(sourceProfile, original);
  assert.equal(Object.hasOwn(sourceProfile.stats, 'ranking_boards'), false);
}

async function testClientSharesRangeRequestAcrossPlayers() {
  let resolveShared;
  const sharedResponse = new Promise((resolve) => { resolveShared = resolve; });
  let sharedRequests = 0;
  const { browser, requests, fetch } = browserFixture({
    profiles: { p1: profile('p1'), p2: profile('p2') },
    onRequest: async (url) => {
      if (url.endsWith('/data/manifest.json')) return response(200, manifest());
      if (url.includes('/rankings/')) {
        sharedRequests += 1;
        return sharedResponse;
      }
      const player = url.match(/\/players\/([^/]+)\/[^/]+\.json$/)?.[1];
      if (player) return response(200, profile(player));
      throw new Error(`Unexpected static request: ${url}`);
    },
  });
  let results;
  await withFetch(fetch, async () => {
    const first = browser.fetchPlayerRange('p1', 'S22', 'S23');
    const second = browser.fetchPlayerRange('p2', 'S22', 'S23');
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(sharedRequests, 1);
    resolveShared(response(200, sharedRankings()));
    results = await Promise.all([first, second]);
  });

  assert.equal(sharedRequests, 1);
  assert.equal(requests.filter(({ url }) => url.includes('/rankings/')).length, 1);
  assert.deepEqual(results.map((item) => item.id), ['p1', 'p2']);
}

async function testClientRetriesRejectedSharedRequest() {
  let sharedRequests = 0;
  const { browser, requests, fetch } = browserFixture({
    profiles: { p1: profile('p1') },
    onRequest: async (url) => {
      if (url.endsWith('/data/manifest.json')) return response(200, manifest());
      if (url.includes('/rankings/')) {
        sharedRequests += 1;
        return sharedRequests === 1 ? response(503, {}) : response(200, sharedRankings());
      }
      const player = url.match(/\/players\/([^/]+)\/[^/]+\.json$/)?.[1];
      if (player) return response(200, profile(player));
      throw new Error(`Unexpected static request: ${url}`);
    },
  });

  await withFetch(fetch, async () => {
    await assert.rejects(browser.fetchPlayerRange('p1', 'S22', 'S23'), (error) => error.kind === 'unavailable');
    await new Promise((resolve) => setImmediate(resolve));
    const result = await browser.fetchPlayerRange('p1', 'S22', 'S23');
    assert.deepEqual(result.stats.ranking_boards, sharedRankings().ranking_boards);
  });

  assert.equal(sharedRequests, 2);
  assert.equal(requests.filter(({ url }) => url.includes('/rankings/')).length, 2);
}

async function testClientRejectsMixedReleaseOrScope() {
  const cases = [
    ['release', sharedRankings({ release_id: 'other-release' })],
    ['scope', sharedRankings({ scope: scope({ season_end: 'S24' }) })],
  ];
  for (const [label, shared] of cases) {
    const { browser, fetch } = browserFixture({ profiles: { p1: profile('p1') }, shared });
    await withFetch(fetch, async () => {
      await assert.rejects(browser.fetchPlayerRange('p1', 'S22', 'S23'),
        (error) => error.kind === 'invalid', `mixed ${label} should be rejected`);
    });
  }
}

async function testClientSchemaOneSkipsSharedFile() {
  const { browser, requests, fetch } = browserFixture({
    schemaVersion: 1,
    profiles: { p1: profile('p1') },
    onRequest: async (url) => {
      if (url.endsWith('/data/manifest.json')) return response(200, manifest(1));
      const player = url.match(/\/players\/([^/]+)\/[^/]+\.json$/)?.[1];
      if (player) return response(200, profile(player));
      throw new Error(`Schema 1 must not request shared rankings: ${url}`);
    },
  });
  const result = await withFetch(fetch, () => browser.fetchPlayerRange('p1', 'S22', 'S23'));

  assert.equal(result.id, 'p1');
  assert.equal(Object.hasOwn(result.stats, 'ranking_boards'), false);
  assert.equal(requests.filter(({ url }) => url.endsWith('/data/manifest.json')).length, 1);
  assert.equal(requests.filter(({ url }) => url.includes('/releases/')).length, 1);
  assert.equal(requests.some(({ url }) => url.includes('/rankings/')), false);
}

async function main() {
  await testClientMergesSharedRankingsWithoutMutatingProfile();
  await testClientSharesRangeRequestAcrossPlayers();
  await testClientRetriesRejectedSharedRequest();
  await testClientRejectsMixedReleaseOrScope();
  await testClientSchemaOneSkipsSharedFile();
  console.log('Static shared player ranking checks passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
