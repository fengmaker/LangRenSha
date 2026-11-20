import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const manifestPath = new URL("./static-browser.ts", import.meta.url);
const playerBrowserPath = new URL("../app/players/[id]/static-player-browser.tsx", import.meta.url);
const playersBrowserPath = new URL("../app/players/static-players-browser.tsx", import.meta.url);
const siteModePath = new URL("./site-mode.ts", import.meta.url);

class ApiError extends Error {
  constructor(kind, message) {
    super(message);
    this.kind = kind;
  }
}

function loadSource(url, imports, globals = {}) {
  const source = readFileSync(url, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  });
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    require: (name) => {
      if (Object.hasOwn(imports, name)) return imports[name];
      throw new Error(`Unexpected import: ${name}`);
    },
    URLSearchParams,
    ...globals,
  });
  vm.runInContext(outputText, context, { filename: url.pathname });
  return module.exports;
}

function manifest(snapshotId, overrides = {}) {
  return { schema_version: 2, snapshot_id: snapshotId, seasons: [{ id: "S22" }, { id: "S23" }], ...overrides };
}

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function staticBrowser(fetch, location = { reload() {} }, basePath = "", globals = {}) {
  return loadSource(manifestPath, {
    "@/lib/site-mode": {
      basePath,
      publicPath: (path) => basePath && !path.startsWith(`${basePath}/`) ? `${basePath}${path}` : path,
    },
    "@/lib/api-error": { ApiError },
    "@/lib/player-rankings": { restorePlayerRankings: (profile) => ({ ...profile, rankings_restored: true }) },
  }, { fetch, window: { location }, ...globals });
}

test("a 404 with a newer snapshot reloads the unchanged filtered URL", async () => {
  const requests = [];
  const location = {
    href: "https://archive.example/leaderboard?season=S22&phase=finals_week",
    reloads: [],
    reload() { this.reloads.push(this.href); },
  };
  const fetch = async (url) => {
    requests.push(url);
    if (url.endsWith("manifest.json")) return response(200, manifest(requests.filter((item) => item.endsWith("manifest.json")).length === 1 ? "old" : "new"));
    return url.includes("removed.json") ? response(404, {}) : response(200, { snapshot: url.includes("/old/") ? "old" : "new" });
  };
  const browser = staticBrowser(fetch, location);

  await assert.rejects(browser.fetchStaticJson("removed.json"), (error) => error.kind === "unavailable");
  assert.deepEqual(await browser.fetchStaticJson("still-present.json"), { snapshot: "old" });
  assert.deepEqual(location.reloads, ["https://archive.example/leaderboard?season=S22&phase=finals_week"]);
  assert.equal(requests.filter((item) => item.includes("/releases/")).length, 2);
  assert.equal(requests.filter((item) => item.endsWith("manifest.json")).length, 2);
});

test("a 404 with the same snapshot reports the missing relative path", async () => {
  const requests = [];
  const browser = staticBrowser(async (url) => {
    requests.push(url);
    return url.endsWith("manifest.json") ? response(200, manifest("same")) : response(404, {});
  });

  await assert.rejects(browser.fetchStaticJson("players/missing.json"), (error) => error.kind === "not-found" && error.message.includes("players/missing.json"));
  assert.equal(requests.filter((item) => item.endsWith("manifest.json")).length, 2);
});

test("unchanged documents reuse their URL across snapshots and report the selected release", async () => {
  const digest = "a".repeat(64);
  const path = "games/game-1.json";
  const requests = [];
  for (const release of ["old", "new"]) {
    const browser = staticBrowser(async (url, { cache }) => {
      if (url.endsWith("/manifest.json")) return response(200, manifest(release, {
        schema_version: 3, release_id: release, document_hashes: { [path]: digest },
      }));
      requests.push([url, cache]);
      return response(200, { id: "game-1" });
    }, undefined, "/archive");

    const game = await browser.fetchGame("game-1");
    assert.equal(game.id, "game-1");
    assert.equal(game.release_id, release);
  }
  const request = [`/archive/data/objects/${digest}.json`, "force-cache"];
  assert.deepEqual(requests, [request, request]);
});

test("a missing content-addressed document refreshes a superseded snapshot", async () => {
  const digest = "a".repeat(64);
  let refreshed = false;
  let reads = 0;
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("/manifest.json")) return response(200, manifest(++reads === 1 ? "old" : "new", {
      schema_version: 3, document_hashes: { "games/game-1.json": digest },
    }));
    assert.equal(url, `/data/objects/${digest}.json`);
    return response(404, {});
  }, { reload() { refreshed = true; } });

  await assert.rejects(browser.fetchGame("game-1"), (error) => error.kind === "unavailable");
  assert.equal(refreshed, true);
});

test("a failed first manifest request is not retained in the promise cache", async () => {
  let manifestRequests = 0;
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("manifest.json")) {
      manifestRequests += 1;
      return manifestRequests === 1 ? response(503, {}) : response(200, manifest("available"));
    }
    return response(200, { ok: true });
  });

  await assert.rejects(browser.fetchSnapshotManifest(), (error) => error.kind === "unavailable");
  assert.equal((await browser.fetchSnapshotManifest()).snapshot_id, "available");
  assert.equal(manifestRequests, 2);
});

test("season player photos use mapped thumbnails and keep unmapped legacy URLs", async () => {
  const original = "/media/player-photos/S23/source.jpg";
  const thumbnail = "/media/player-photos/S23/thumb.webp";
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("manifest.json")) return response(200, manifest("photos", { player_photo_thumbnails: { [original]: thumbnail } }));
    return response(200, {
      items: [
        { id: "mapped", photo: { url: original, season: "S23", source_url: "https://example.test/a", source_date: "2026-01-01" },
          appearances: 4, stats: { appearances: 3, wins: 1, losses: 0, total_win_rate: { rate: null }, ranking_boards: {} } },
        { id: "legacy", photo: { url: "/media/player-photos/S22/legacy.jpg", season: "S22", source_url: "https://example.test/b", source_date: "2025-01-01" } },
      ],
      total: 2,
      page: 1,
      page_size: 20,
      release_id: "r1",
    });
  }, undefined, "/archive");

  const result = await browser.fetchPlayersForSeason("S23");
  assert.equal(result.items[0].photo.url, thumbnail);
  assert.equal(result.items[0].photo.original_url, undefined);
  assert.equal(result.items[0].appearances, 3);
  assert.equal(result.items[0].stats.win_rate, null);
  assert.equal(result.items[0].stats.ranking_boards, undefined);
  assert.equal(result.items[1].photo.url, "/media/player-photos/S22/legacy.jpg");
});

test("the latest schema reads lightweight player cards from an immutable URL", async () => {
  const digest = "b".repeat(64);
  const thumbnail = "/media/player-photos/S23/thumb.webp";
  const item = { id: "p1", name: "Player One", appearances: 3, photo: { url: thumbnail, season: "S23" },
    stats: { wins: 2, losses: 1, win_rate: 2 / 3 } };
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("/manifest.json")) return response(200, manifest("directory", {
      schema_version: 3, release_id: "r3", document_hashes: { "players/by-season/S23.json": digest },
    }));
    assert.equal(url, `/data/objects/${digest}.json`);
    return response(200, { items: [item], total: 1, page: 1, page_size: 1 });
  });

  const result = await browser.fetchPlayersForSeason("S23");
  assert.equal(result.items[0], item);
  assert.equal(result.release_id, "r3");
});


test("older manifests without a thumbnail map keep the original player photo URL", async () => {
  const original = "/media/player-photos/S22/legacy.jpg";
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("manifest.json")) return response(200, manifest("legacy", { schema_version: 1 }));
    return response(200, {
      items: [{ id: "legacy", photo: { url: original, season: "S22", source_url: "https://example.test/a", source_date: "2025-01-01" } }],
      total: 1,
      page: 1,
      page_size: 20,
      release_id: "r1",
    });
  });

  const result = await browser.fetchPlayersForSeason("S22");
  assert.equal(result.items[0].photo.url, original);
});

test("player profile uses the thumbnail and preloads it before shared rankings resolve", async () => {
  const original = "/media/player-photos/S23/source.jpg";
  const thumbnail = "/media/player-photos/S23/thumb.webp";
  const links = [];
  let resolveRankings;
  let rankingRequested;
  const rankingRequest = new Promise((resolve) => { resolveRankings = resolve; });
  const rankingsStarted = new Promise((resolve) => { rankingRequested = resolve; });
  const document = {
    createElement: (tagName) => ({ tagName, getAttribute(name) { return this[name] ?? null; } }),
    head: {
      querySelectorAll: () => links,
      append(link) { links.push(link); },
    },
  };
  const browser = staticBrowser(async (url) => {
    if (url.endsWith("manifest.json")) return response(200, manifest("profile", { schema_version: 3, document_hashes: {} }));
    if (url.includes("/rankings/")) {
      rankingRequested();
      return rankingRequest;
    }
    return response(200, {
      id: "p1",
      name: "Player One",
      release_id: "r1",
      photo: { url: thumbnail, original_url: original, season: "S23", source_url: "https://example.test/a", source_date: "2026-01-01" },
    });
  }, undefined, "/archive", { document });

  const request = browser.fetchPlayerRange("p1", "2026", "2026");
  await rankingsStarted;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(links.length, 2);
  const previewPreload = links.find((link) => link.href === `/archive${thumbnail}`);
  const originalPreload = links.find((link) => link.href === `/archive${original}`);
  assert.equal(previewPreload.rel, "preload");
  assert.equal(previewPreload.as, "image");
  assert.equal(originalPreload.rel, "preload");
  assert.equal(originalPreload.as, "image");
  assert.equal(originalPreload.fetchPriority, "high");

  resolveRankings(response(200, {}));
  const result = await request;
  assert.equal(result.photo.url, thumbnail);
  assert.equal(result.photo.original_url, original);
  assert.equal(result.rankings_restored, true);
});

test("the leaderboard requests the selected summary and reuses on-demand samples from its HTML snapshot", async () => {
  const requests = [];
  const browser = staticBrowser(async (url) => {
    requests.push(url);
    return response(200, {});
  });

  const relativePath = "/data/releases/prerendered/leaderboards/S22/finals_week";
  await browser.fetchLeaderboard("prerendered", "S22", "finals_week");
  assert.deepEqual(requests, [relativePath + ".summary.json"]);
  const samples = browser.fetchLeaderboardSamples("prerendered", "S22", "finals_week");
  assert.equal(browser.fetchLeaderboardSamples("prerendered", "S22", "finals_week"), samples);
  await samples;
  assert.deepEqual(requests, [relativePath + ".summary.json", relativePath + ".json"]);
});

test("the player profile first request follows the URL season", async () => {
  const playerRequests = [];
  const snapshot = { seasons: [{ id: "S21" }, { id: "S22" }, { id: "S23" }] };
  const jsx = (type, props) => ({ type, props });
  const browser = loadSource(playerBrowserPath, {
    "@/components/static-data": { StaticData() {} },
    "next/navigation": { useSearchParams() {} },
    react: { useEffect() {}, useState() {} },
    "@/lib/static-browser": {
      fetchSnapshotManifest: async () => snapshot,
      fetchPlayerRange: async (id, start, end) => {
        playerRequests.push([id, start, end]);
        return { id, name: "Player One", scope: { season_start: start, season_end: end } };
      },
      staticRouteId: () => "p1",
      updateStaticQuery() {},
    },
    "./player-profile-view": { PlayerProfileView() {} },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: Symbol("Fragment") },
  }, {
    window: { location: { pathname: "/players/p1", search: "?season=S21" } },
    document: { title: "" },
  });

  const element = browser.StaticPlayerBrowser();
  const loaded = await element.props.load();
  assert.deepEqual(playerRequests, [["p1", "S21", "S21"]]);
  assert.equal(loaded.initialPlayer.scope.season_start, "S21");
});

test("static page URLs keep query strings and fragments after the trailing slash", () => {
  const siteMode = loadSource(siteModePath, {}, { process: { env: {
    NEXT_PUBLIC_SITE_MODE: "static",
    NEXT_PUBLIC_BASE_PATH: "/archive",
  } } });
  const local = loadSource(siteModePath, {}, { process: { env: {} } });

  assert.equal(siteMode.publicPagePath("/"), "/archive/");
  assert.equal(siteMode.publicPagePath("/players/p1?season=S23#results"), "/archive/players/p1/?season=S23#results");
  assert.equal(siteMode.publicPagePath("/archive/games/"), "/archive/games/");
  assert.equal(siteMode.publicPagePath("//example.org/other"), "//example.org/other");
  assert.equal(siteMode.publicPagePath("#results"), "#results");
  assert.equal(siteMode.publicPath("/media/portrait.webp"), "/archive/media/portrait.webp");
  assert.equal(local.publicPagePath("/players?season=S23"), "/players?season=S23");
});

test("the player directory requests the season index while the overview is pending", async () => {
  const requests = [];
  const overview = { seasons: [{ id: "S23", name: "Season 23" }] };
  let finishOverview;
  const pendingOverview = new Promise((resolve) => { finishOverview = resolve; });
  const directory = staticBrowser(async (url) => {
    requests.push(url);
    if (url.endsWith("/manifest.json")) return response(200, manifest("directory"));
    if (url.endsWith("/overview.json")) return pendingOverview;
    if (url.endsWith("/players/by-season/S23.json")) return response(200, { items: [], total: 0 });
    throw new Error(`Unexpected request: ${url}`);
  });
  const jsx = (type, props) => ({ type, props });
  const browser = loadSource(playersBrowserPath, {
    "@/components/static-data": { StaticData() {} },
    "@/components/archive-link": {},
    "next/navigation": {},
    react: {},
    "@/lib/static-browser": directory,
    "@/lib/site-mode": {},
    "@/lib/query-state": {},
    "@/components/pagination": {},
    "@/components/page-intro": {},
    "@/lib/format": {},
    "./players.module.css": {},
    "react/jsx-runtime": { jsx, jsxs: jsx },
  });

  const pending = browser.StaticPlayersBrowser().props.load();
  await new Promise(setImmediate);
  const started = [...requests];
  finishOverview(response(200, overview));
  const loaded = await pending;

  assert.deepEqual(started, [
    "/data/manifest.json",
    "/data/releases/directory/overview.json",
    "/data/releases/directory/players/by-season/S23.json",
  ]);
  assert.equal(loaded.overview, overview);
  assert.equal(loaded.initialSeason, "S23");
});
