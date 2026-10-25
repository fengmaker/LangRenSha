const DECISIONS = new Set(["", "yes", "no", "later", "uncertain", "comment"]);
const ID_PATTERN = /^BV[0-9A-Za-z]{10}:(?:[1-9]|1[0-2])$/;
const KIND = "s22_bluff_feedback";

function filled(record) {
  return Boolean(record && (record.decision || record.notes?.trim()));
}

function readRecords(value, season) {
  if (!value || value.kind !== KIND || value.schema_version !== 1 || value.season !== season || !Array.isArray(value.records)) {
    throw new Error("这不是当前赛季的悍跳反馈文件。");
  }
  const records = {};
  for (const row of value.records) {
    if (!row || !ID_PATTERN.test(row.review_id) || !DECISIONS.has(row.decision) || typeof row.notes !== "string" || row.notes.length > 4000
        || !/^[a-f0-9]{64}$/.test(row.source_fingerprint || "") || ![null, "预言家", "通灵师"].includes(row.claimed_role)
        || ![null, 1, 2, "later"].includes(row.claim_day)) {
      throw new Error("反馈文件中有不完整或不支持的记录，原草稿未改动。");
    }
    records[row.review_id] = row;
  }
  return records;
}

function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  try {
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  } finally {
    anchor.remove();
  }
}

export function mountBluffFeedback(root, options) {
  const key = `masters-archive:bluff-feedback:${options.season}:v1`;
  const forms = Array.from(root.querySelectorAll("form.bluff-feedback-form"));
  const status = root.querySelector("[data-feedback-status]");
  const copyFallback = root.querySelector("[data-feedback-copy-fallback]");
  const copyArea = copyFallback?.querySelector("textarea");
  let records = {};
  let storageWorks = true;
  const listeners = [];
  const envelope = () => ({ kind: KIND, schema_version: 1, season: options.season,
    inference_version: options.inference_version || null, exported_at: new Date().toISOString(),
    records: Object.values(records).filter(filled).sort((a, b) => a.review_id.localeCompare(b.review_id)) });

  function say(message = "") {
    const count = forms.filter((form) => filled(records[form.dataset.reviewId])).length;
    const total = Object.values(records).filter(filled).length;
    if (status) status.textContent = `本页已填写 ${count} / ${forms.length} 条；共保存 ${total} 条。${message || (storageWorks ? "已自动保存草稿。" : "浏览器未能保存草稿，请导出反馈文件保存。")}`;
  }

  function merge(next) {
    for (const [id, row] of Object.entries(next)) {
      if (!records[id] || String(row.updated_at || "") >= String(records[id].updated_at || "")) records[id] = row;
    }
  }

  try {
    const saved = localStorage.getItem(key);
    if (saved) merge(readRecords(JSON.parse(saved), options.season));
  } catch { storageWorks = false; }
  const embedded = root.querySelector("#bluff-feedback-embedded");
  if (embedded?.textContent) {
    try { merge(readRecords(JSON.parse(embedded.textContent), options.season)); }
    catch { say("内嵌反馈无法读取，已有浏览器草稿仍保留。"); }
  }

  function restore() {
    for (const form of forms) {
      const row = records[form.dataset.reviewId];
      const decision = form.elements.namedItem("decision");
      const role = form.elements.namedItem("claimed_role");
      const day = form.elements.namedItem("claim_day");
      const notes = form.elements.namedItem("notes");
      if (row) {
        decision.value = row.decision;
        role.value = row.claimed_role || "";
        day.value = row.claim_day == null ? "" : String(row.claim_day);
        if (notes.value !== row.notes) notes.value = row.notes;
      }
      form.dataset.feedbackFilled = filled(row) ? "true" : "false";
      const stale = row && row.source_fingerprint !== form.dataset.fingerprint;
      const hint = form.querySelector("[data-feedback-row-status]");
      const incompleteYes = row?.decision === "yes"
        && (!row.claim_day || !["预言家", "通灵师"].includes(row.claimed_role));
      if (hint) hint.textContent = stale ? "这条反馈对应的原始记录已变化，请重新核对后选择结论。"
        : incompleteYes ? "结论已保存；所跳身份或天数待补，导出时会保留为空。"
        : filled(row) ? "本条草稿已保存" : "尚未填写";
    }
  }

  function persist(message) {
    try { localStorage.setItem(key, JSON.stringify(envelope())); storageWorks = true; }
    catch { storageWorks = false; }
    restore();
    say(message);
  }

  function capture(form) {
    const decision = form.elements.namedItem("decision").value;
    const notes = form.elements.namedItem("notes").value.slice(0, 4000);
    const role = form.elements.namedItem("claimed_role").value || null;
    const dayValue = form.elements.namedItem("claim_day").value;
    const claimDay = dayValue === "1" || dayValue === "2" ? Number(dayValue) : dayValue || null;
    const previous = records[form.dataset.reviewId];
    if (previous && previous.decision === decision && previous.notes === notes
        && previous.claimed_role === role && previous.claim_day === claimDay) return;
    if (!decision && !notes.trim()) delete records[form.dataset.reviewId];
    else records[form.dataset.reviewId] = {
      review_id: form.dataset.reviewId, game_id: form.dataset.gameId,
      bvid: form.dataset.bvid, seat: Number(form.dataset.seat), name: form.dataset.name,
      physical_role: form.dataset.physicalRole, source_fingerprint: form.dataset.fingerprint,
      inference_version: options.inference_version || null, decision,
      claimed_role: role,
      claim_day: claimDay,
      notes, updated_at: new Date().toISOString(),
    };
  }

  function captureAll() { forms.forEach(capture); }
  function exportText() {
    captureAll();
    persist();
    return JSON.stringify(envelope(), null, 2);
  }
  function incompleteYesCount() {
    return Object.values(records).filter((row) => row.decision === "yes"
      && (!row.claim_day || !["预言家", "通灵师"].includes(row.claimed_role))).length;
  }
  function exportNotice() {
    const incomplete = incompleteYesCount();
    return incomplete
      ? `其中 ${incomplete} 条“确认是悍跳”尚未填写身份或天数；已原样导出，空缺字段保持未确定，请补充核对。未填写不代表确认。`
      : "未填写不代表确认。";
  }
  function revealCopyFallback(text) {
    if (!copyFallback || !copyArea) return false;
    copyArea.value = text;
    copyFallback.hidden = false;
    copyArea.focus();
    copyArea.select();
    return true;
  }
  async function copyFeedback(text) {
    revealCopyFallback(text);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
      await navigator.clipboard.writeText(text);
      say("完整反馈 JSON 已复制；如无法粘贴，也可手动复制下方文本。");
    } catch {
      copyArea?.focus();
      copyArea?.select();
      say("浏览器未开放剪贴板权限。完整反馈 JSON 已展开并选中，请手动复制下方文本。");
    }
  }
  function on(element, event, callback) {
    element.addEventListener(event, callback);
    listeners.push(() => element.removeEventListener(event, callback));
  }
  for (const form of forms) {
    on(form, "submit", (event) => event.preventDefault());
    const update = () => { capture(form); persist(); };
    on(form, "input", update);
    on(form, "change", update);
  }
  root.querySelectorAll("[data-feedback-save]").forEach((button) => on(button, "click", () => { captureAll(); persist("草稿已保存。填写完后请导出反馈文件发给我。"); }));
  root.querySelectorAll("[data-feedback-export]").forEach((button) => on(button, "click", () => {
    const text = exportText();
    try {
      download(`${options.season}_悍跳复核反馈.json`, text, "application/json;charset=utf-8");
      say(`反馈文件已导出。${exportNotice()}请把这个 JSON 文件发给我，或告诉我保存路径。`);
    } catch {
      revealCopyFallback(text);
      say(`浏览器未能启动文件下载，完整 JSON 已展开并选中，可手动复制。${exportNotice()}`);
    }
  }));
  root.querySelectorAll("[data-feedback-copy-open]").forEach((button) => on(button, "click", () => {
    void copyFeedback(exportText());
  }));
  root.querySelectorAll("[data-feedback-copy]").forEach((button) => on(button, "click", () => {
    void copyFeedback(exportText());
  }));
  root.querySelectorAll("[data-feedback-backup]").forEach((button) => on(button, "click", () => {
    const text = exportText();
    const clone = document.documentElement.cloneNode(true);
    clone.querySelector("#bluff-feedback-embedded")?.remove();
    const seed = document.createElement("script");
    seed.id = "bluff-feedback-embedded"; seed.type = "application/json";
    seed.textContent = text.replace(/</g, "\\u003c");
    clone.querySelector("head").append(seed);
    try {
      download(`${options.season}_悍跳复核_已填写.html`, "<!doctype html>\n" + clone.outerHTML, "text/html;charset=utf-8");
      say(`已下载包含填写内容的复核页。${exportNotice()}`);
    } catch {
      revealCopyFallback(text);
      say(`浏览器未能启动复核页下载；完整 JSON 已展开并选中，可手动复制。${exportNotice()}`);
    }
  }));
  root.querySelectorAll("[data-feedback-import]").forEach((input) => on(input, "change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    try {
      if (file.size > 5_000_000) throw new Error("反馈文件过大，请选择导出的悍跳反馈 JSON。");
      const next = readRecords(JSON.parse(await file.text()), options.season);
      merge(next); persist(`已导入 ${Object.keys(next).length} 条反馈；可继续填写。`);
    } catch (error) { say(error instanceof Error ? error.message : "反馈文件无法读取，原草稿未改动。"); }
    input.value = "";
  }));
  restore(); say();
  return () => { listeners.forEach((remove) => remove()); };
}
