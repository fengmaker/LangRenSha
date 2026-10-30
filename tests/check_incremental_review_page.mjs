import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const [soloPath, batchPath] = process.argv.slice(2);
assert(soloPath && batchPath, 'pass the single-game and expanded-batch HTML paths');

function elements() {
  return { listeners: new Map(), addEventListener(name, handler) { this.listeners.set(name, handler); } };
}

function makePage(html, storage) {
  const dataTag = html.match(/<script id="review-data" type="application\/json">([\s\S]*?)<\/script>/);
  assert(dataTag, 'review manifest exists');
  const data = JSON.parse(dataTag[1]);
  const appScript = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    .find(([, attrs]) => !/type=["']application\/json["']/i.test(attrs));
  assert(appScript, 'application script exists');
  const cards = new Map(data.games.map(game => {
    const note = { ...elements(), value: '' };
    const reviewed = { ...elements(), checked: false };
    return [game.review_id, {
      dataset: { reviewId: game.review_id },
      querySelector(selector) { return selector === '[data-note]' ? note : reviewed; },
      note,
      reviewed,
    }];
  }));
  const status = { textContent: '' };
  const exportButton = elements();
  const importInput = elements();
  const reviewData = { textContent: JSON.stringify(data) };
  let savedBlob;
  const downloads = [];
  const blobs = new Map();
  const document = {
    getElementById(id) {
      return ({ 'review-data': reviewData, status, export: exportButton, 'import-file': importInput })[id];
    },
    querySelectorAll() { return [...cards.values()]; },
    createElement(tag) {
      assert.equal(tag, 'a');
      return {
        click() { downloads.push({ download: this.download, blob: blobs.get(this.href) }); },
      };
    },
  };
  const URLStub = {
    createObjectURL(blob) { savedBlob = blob; const key = `blob:qa-${blobs.size}`; blobs.set(key, blob); return key; },
    revokeObjectURL() {},
  };
  vm.runInNewContext(appScript[2], {
    document, localStorage: storage, URL: URLStub, Blob, JSON, Map, Array, Object, Set, String,
    encodeURIComponent,
  });
  return { data, cards, status, exportButton, importInput, downloads,
    savedBlob: () => savedBlob };
}

function edit(card, note, reviewed) {
  card.note.value = note;
  card.note.listeners.get('input')();
  card.reviewed.checked = reviewed;
  card.reviewed.listeners.get('change')();
}

async function importPayload(page, payload) {
  const event = { target: { files: [{ text: async () => JSON.stringify(payload) }], value: 'selected.json' } };
  await page.importInput.listeners.get('change')(event);
}

const soloHtml = await fs.readFile(soloPath, 'utf8');
const batchHtml = await fs.readFile(batchPath, 'utf8');
const stored = new Map();
const storage = {
  getItem(key) { return stored.has(key) ? stored.get(key) : null; },
  setItem(key, value) { stored.set(key, String(value)); },
  removeItem(key) { stored.delete(key); },
};
const solo = makePage(soloHtml, storage);
const id = solo.data.games[0].review_id;
edit(solo.cards.get(id), '自动草稿', true);

// Loading an expanded batch reuses the first game's per-identity/per-version draft.
const page = makePage(batchHtml, storage);
assert.equal(page.cards.get(id).note.value, '自动草稿');
assert.equal(page.cards.get(id).reviewed.checked, true);
const secondId = page.data.games.find(game => game.review_id !== id).review_id;
assert.equal(page.cards.get(secondId).note.value, '');
assert.equal(page.cards.get(secondId).reviewed.checked, false);
edit(page.cards.get(secondId), '第二局保留草稿', true);

page.exportButton.listeners.get('click')();
assert.equal(page.downloads.length, 1);
const exported = JSON.parse(await page.downloads[0].blob.text());
assert.deepEqual(Object.keys(exported).sort(), ['format', 'games', 'season']);
assert.equal(exported.format, 'masters-incremental-review-v1');
assert.equal(exported.season, page.data.season);
assert.equal(exported.games.length, 2);
const gameKeys = ['bvid', 'candidate_sha256', 'cid', 'note', 'page', 'review_id', 'reviewed', 'source_sha256'];
assert.deepEqual(Object.keys(exported.games[0]).sort(), gameKeys);
assert.equal(exported.games[0].note, '自动草稿');
assert.equal(exported.games[0].reviewed, true);

// Importing a subset updates that game while leaving omitted game drafts alone.
const currentA = page.data.games.find(game => game.review_id === id);
const subsetItem = { ...currentA, reviewed: false, note: '子集导入' };
await importPayload(page, { format: exported.format, season: exported.season, games: [subsetItem] });
assert.equal(page.cards.get(id).note.value, '子集导入');
assert.equal(page.cards.get(id).reviewed.checked, false);
assert.equal(page.cards.get(secondId).note.value, '第二局保留草稿');
assert.equal(page.cards.get(secondId).reviewed.checked, true);

const snapshot = new Map(stored);
const unchanged = ['子集导入', false];
const wrongVersion = { ...page.data.games.find(game => game.review_id === secondId), reviewed: false, note: '不应写入' };
wrongVersion.source_sha256 = 'changed-source';
await importPayload(page, { format: exported.format, season: exported.season, games: [
  { ...currentA, reviewed: true, note: '不应部分写入' }, wrongVersion,
] });
assert.match(page.status.textContent, /导入未完成/);
assert.equal(page.cards.get(id).note.value, unchanged[0]);
assert.equal(page.cards.get(id).reviewed.checked, unchanged[1]);
assert.deepEqual(new Map(stored), snapshot, 'version failure leaves local storage untouched');

await importPayload(page, { format: exported.format, season: exported.season, games: [
  { ...currentA, reviewed: true, note: '不应重复写入' }, { ...currentA, reviewed: false, note: '重复' },
] });
assert.match(page.status.textContent, /导入未完成/);
assert.equal(page.cards.get(id).note.value, unchanged[0]);
assert.equal(page.cards.get(id).reviewed.checked, unchanged[1]);
assert.deepEqual(new Map(stored), snapshot, 'duplicate failure leaves local storage untouched');

console.log(JSON.stringify({ autosave_survives_new_batch: true, export_shape: true,
  subset_import: true, version_rejection_is_atomic: true, duplicate_rejection_is_atomic: true }));
