"use client";

import { useEffect } from "react";
import { mountBluffFeedback } from "@/lib/bluff-feedback-runtime.js";

export function BluffFeedbackTools({ season, inferenceVersion, scopeKey }: {
  season: string; inferenceVersion: string | null; scopeKey: string;
}) {
  useEffect(() => mountBluffFeedback(document, { season, inference_version: inferenceVersion }), [season, inferenceVersion, scopeKey]);
  return <section className="bluff-feedback-tools" aria-label="保存与反馈复核意见">
    <p>逐条选择结论并填写意见。已确认悍跳的项目可另外确认成功、失败或待定；留空表示本次没有复核成功。草稿会保存在当前浏览器，导出后交由人工复核构建器应用。</p>
    <div><button type="button" className="button" data-feedback-save>保存草稿</button><button type="button" className="button button-primary" data-feedback-export>导出反馈 JSON</button><button type="button" className="button" data-feedback-copy-open>显示／复制反馈 JSON</button><label className="button">导入反馈<input type="file" accept=".json,application/json" data-feedback-import hidden /></label></div>
    <p data-feedback-status role="status" aria-live="polite">正在读取本地草稿…</p>
    <div className="bluff-feedback-copy-fallback" data-feedback-copy-fallback hidden>
      <p>如果浏览器没有开始下载，请复制下面的完整反馈 JSON，再发给维护者。</p>
      <textarea aria-label="可复制的完整反馈 JSON" data-feedback-copy-text readOnly spellCheck={false} />
      <button type="button" className="button" data-feedback-copy>复制 JSON</button>
    </div>
  </section>;
}
