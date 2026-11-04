import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const manifestPath = new URL("./static-browser.ts", import.meta.url);
const leaderboardPath = new URL("../app/leaderboard/static-leaderboard-browser.tsx", import.meta.url);

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

function manifest(snapshotId) {
  return { snapshot_id: snapshotId, seasons: [{ id: "S22" }, { id: "S23" }] };
}

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function staticBrowser(fetch, location = { reload() {} }) {
  return loadSource(manifestPath, {
    "@/lib/site-mode": { basePath: "" },
    "@/lib/api-error": { ApiError },
  }, { fetch, window: { location } });
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

test("the leaderboard first request follows the URL season and phase", async () => {
  const leaderboardRequests = [];
  const snapshot = {
    seasons: [
      { id: "S22", phases: ["all", "finals_week"] },
      { id: "S23", phases: ["all"] },
    ],
  };
  const jsx = (type, props) => ({ type, props });
  const browser = loadSource(leaderboardPath, {
    "@/components/static-data": { StaticData() {} },
    "next/navigation": { useSearchParams() {} },
    react: { useEffect() {}, useState() {} },
    "@/lib/static-browser": {
      fetchSnapshotManifest: async () => snapshot,
      fetchOverview: async () => ({}),
      fetchLeaderboard: async (season, phase) => {
        leaderboardRequests.push([season, phase]);
        return { season, phase };
      },
      updateStaticQuery() {},
    },
    "./leaderboard-view": { LeaderboardView() {} },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: Symbol("Fragment") },
  }, {
    window: { location: { search: "?season=S22&phase=finals_week" } },
  });

  const element = browser.StaticLeaderboardBrowser();
  const loaded = await element.props.load();
  assert.equal(loaded.initialSeason, "S22");
  assert.deepEqual(leaderboardRequests, [["S22", "finals_week"]]);
});
