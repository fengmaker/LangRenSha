"use client";

import Link from "next/link";
import { useId, useRef, useState, type ReactNode } from "react";
import type { Metric, PlayerLedgerEntry } from "@/lib/types";
import { formatDate, formatNumber } from "@/lib/format";

export type SampleLabels = { positive: string; negative: string; unit: "场" | "次"; description: string };
export type MetricSampleGame = Pick<PlayerLedgerEntry, "game_id" | "season" | "date" | "game_number" | "board_name" | "role">;
export type SampleMetric = Pick<Metric, "numerator" | "denominator" | "excluded" | "samples">;

export function MetricSamples({ label, metric, games, labels, trigger }: { label: string; metric: SampleMetric; games: MetricSampleGame[]; labels: SampleLabels; trigger?: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [kind, setKind] = useState<"positive" | "negative">("positive");
  const [hasOpened, setHasOpened] = useState(false);
  const samples = new Map((metric.samples ?? []).map((sample) => [sample.game_id, sample]));
  const rows = games.filter((game) => (samples.get(game.game_id)?.[kind] ?? 0) > 0)
    .sort((a, b) => b.date.localeCompare(a.date) || (b.game_number ?? 0) - (a.game_number ?? 0));
  const counts = { positive: 0, negative: 0 };
  for (const sample of samples.values()) { counts.positive += sample.positive; counts.negative += sample.negative; }
  const resultLabel = labels[kind];

  function open() {
    setKind("positive");
    setHasOpened(true);
    dialog.current?.showModal();
  }

  return <div className="profile-sample-control">
    <button className="sample-trigger" type="button" aria-haspopup="dialog" aria-label={`${label}：查看样本`} onClick={open}>{trigger ?? <>查看样本 <span aria-hidden="true">↗</span></>}</button>
    <dialog ref={dialog} className="sample-dialog" aria-labelledby={titleId} onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
      {hasOpened ? <><header className="sample-dialog-header"><h2 id={titleId}>{label} · 样本</h2><button className="sample-close" type="button" aria-label="关闭样本" onClick={() => dialog.current?.close()}>×</button></header>
      <p className="sample-description">{labels.description}</p>
      <div className="sample-switch" role="group" aria-label="样本类型">
        <button type="button" aria-pressed={kind === "positive"} onClick={() => setKind("positive")}>正面样本 <span>{formatNumber(counts.positive)} {labels.unit}</span></button>
        <button type="button" aria-pressed={kind === "negative"} onClick={() => setKind("negative")}>负面样本 <span>{formatNumber(counts.negative)} {labels.unit}</span></button>
      </div>
      <p className="sample-count">{formatNumber(rows.length)} 局{labels.unit === "次" ? ` · ${formatNumber(counts[kind])} 次${resultLabel}` : ""} · 最新对局在前</p>
      {rows.length ? <ul className="sample-game-list">{rows.map((game) => {
        const sample = samples.get(game.game_id)!;
        return <li key={game.game_id}><Link href={`/games/${encodeURIComponent(game.game_id)}`}>
          <div className="sample-game-main"><strong>{game.season ? `${game.season} · ` : ""}{formatDate(game.date)} · {game.game_number ? `第 ${game.game_number} 局` : game.game_id}</strong><span className={kind === "positive" ? "sample-positive" : "sample-negative"}>{resultLabel}{labels.unit === "次" ? ` ${sample[kind]} 次` : ""}</span></div>
          <div className="sample-game-meta"><span>{game.board_name || "版型待核"} · {game.role || "身份待核"}</span>{sample.positive > 0 && sample.negative > 0 ? <span>本局也有{kind === "positive" ? labels.negative : labels.positive}记录</span> : null}<span aria-hidden="true">查看对局 →</span></div>
        </Link></li>;
      })}</ul> : <p className="sample-empty">当前时间范围内暂无{kind === "positive" ? "正面" : "负面"}样本。</p>}
      {metric.excluded > 0 ? <p className="sample-excluded">另有 {formatNumber(metric.excluded)} 条记录无法判断，未列入正负样本。</p> : null}
      </> : null}
    </dialog>
  </div>;
}
