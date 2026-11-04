import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const runtimeImport = typeof nodeRepl === "undefined"
  ? `data:text/javascript;base64,${Buffer.from(await readFile(new URL("./bluff-feedback-runtime.js", import.meta.url))).toString("base64")}`
  : "./bluff-feedback-runtime.js";
const { mountBluffFeedback } = await import(runtimeImport);

const fingerprints = {
  source: "a".repeat(64),
  claim: "b".repeat(64),
  success: "c".repeat(64),
  currentSource: "d".repeat(64),
  currentClaim: "e".repeat(64),
  currentSuccess: "f".repeat(64),
};

function createFixture({ includeManualSuccess = true } = {}) {
  const storageKey = "masters-archive:bluff-feedback:s22:v1";
  const values = new Map([[storageKey, JSON.stringify({
    kind: "s22_bluff_feedback",
    schema_version: 1,
    season: "s22",
    records: [{
      review_id: "BV0000000000:1",
      game_id: "game-1",
      bvid: "BV0000000000",
      seat: 1,
      name: "玩家",
      physical_role: "狼人",
      source_fingerprint: fingerprints.source,
      claim_fingerprint: fingerprints.claim,
      success_fingerprint: fingerprints.success,
      decision: "yes",
      claimed_role: "预言家",
      claim_day: 1,
      manual_success: true,
      notes: "旧意见",
      updated_at: "2026-01-01T00:00:00.000Z",
    }],
  })]]);
  const fields = Object.fromEntries(["decision", "claimed_role", "claim_day", "notes", "manual_success"]
    .map((name) => [name, { name, value: "" }]));
  const listeners = new Map();
  const buttonListeners = new Map();
  const saveButton = {
    addEventListener: (event, callback) => buttonListeners.set(event, callback),
    removeEventListener: (event) => buttonListeners.delete(event),
  };
  const hint = { textContent: "" };
  const form = {
    dataset: {
      reviewId: "BV0000000000:1",
      gameId: "game-1",
      bvid: "BV0000000000",
      seat: "1",
      name: "玩家",
      physicalRole: "狼人",
      sourceFingerprint: fingerprints.currentSource,
      fingerprint: fingerprints.currentClaim,
      successFingerprint: fingerprints.currentSuccess,
    },
    elements: { namedItem: (name) => name === "manual_success" && !includeManualSuccess ? null : fields[name] ?? null },
    querySelector: () => hint,
    addEventListener: (event, callback) => listeners.set(event, callback),
    removeEventListener: (event) => listeners.delete(event),
  };
  const status = { textContent: "" };
  const root = {
    querySelector: (selector) => selector === "[data-feedback-status]" ? status : null,
    querySelectorAll: (selector) => selector === "form.bluff-feedback-form" ? [form]
      : selector === "[data-feedback-save]" ? [saveButton] : [],
  };
  globalThis.localStorage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  mountBluffFeedback(root, { season: "s22", inference_version: "test" });

  return {
    fields,
    hint,
    saved: () => JSON.parse(values.get(storageKey)).records[0],
    change: (name, value) => {
      fields[name].value = value;
      listeners.get("change")({ target: fields[name] });
    },
    input: (name, value) => {
      fields[name].value = value;
      listeners.get("input")({ target: fields[name] });
    },
    save: () => buttonListeners.get("click")(),
  };
}

const failures = [];
function check(name, run) {
  try {
    run();
    console.log(`ok - ${name}`);
  } catch (error) {
    failures.push(name);
    console.error(`not ok - ${name}: ${error.message}`);
  }
}

check("editing only notes keeps the old source, claim, and success fingerprints", () => {
  const fixture = createFixture();
  fixture.input("notes", "新意见");
  const saved = fixture.saved();

  assert.equal(saved.notes, "新意见");
  assert.equal(saved.source_fingerprint, fingerprints.source);
  assert.equal(saved.claim_fingerprint, fingerprints.claim);
  assert.equal(saved.success_fingerprint, fingerprints.success);
  assert.match(fixture.hint.textContent, /已变化/);
});

check("editing notes without a success control preserves the saved success result", () => {
  const fixture = createFixture({ includeManualSuccess: false });
  fixture.input("notes", "新意见");
  const saved = fixture.saved();

  assert.equal(saved.notes, "新意见");
  assert.equal(saved.manual_success, true);
  assert.equal(saved.success_fingerprint, fingerprints.success);
  assert.match(fixture.hint.textContent, /已变化/);
});

check("reconfirming the unchanged claim decision refreshes only claim fingerprints", () => {
  const fixture = createFixture();
  fixture.change("decision", "yes");
  const saved = fixture.saved();

  assert.equal(saved.decision, "yes");
  assert.equal(saved.source_fingerprint, fingerprints.currentSource);
  assert.equal(saved.claim_fingerprint, fingerprints.currentClaim);
  assert.equal(saved.success_fingerprint, fingerprints.success);
  assert.match(fixture.hint.textContent, /已变化/);
});

check("reconfirming the unchanged success result refreshes only its fingerprint", () => {
  const fixture = createFixture();
  fixture.change("manual_success", "yes");
  const saved = fixture.saved();

  assert.equal(saved.manual_success, true);
  assert.equal(saved.source_fingerprint, fingerprints.source);
  assert.equal(saved.claim_fingerprint, fingerprints.claim);
  assert.equal(saved.success_fingerprint, fingerprints.currentSuccess);
  assert.match(fixture.hint.textContent, /已变化/);
});

check("saving a draft alone does not reconfirm a changed claim selection", () => {
  const fixture = createFixture();
  fixture.fields.decision.value = "no";
  fixture.save();
  const saved = fixture.saved();

  assert.equal(saved.decision, "no");
  assert.equal(saved.source_fingerprint, fingerprints.source);
  assert.equal(saved.claim_fingerprint, fingerprints.claim);
  assert.match(fixture.hint.textContent, /已变化/);
});

if (failures.length) throw new Error(`${failures.length} feedback runtime regression(s) failed.`);
