"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";
import type { MetricRanking, RankingEntry } from "@/lib/types";
import { formatNumber } from "@/lib/format";

export type RankingContext = { playerId: string; start: string; end: string; scopeLabel: string };
export function MetricRank({ ranking, label, provisional, title, entries = [], metricLabel, format = "count", sampleUnit = "场", context }: { ranking?: MetricRanking | null; label?: string; provisional?: boolean; title?: string; entries?: RankingEntry[]; metricLabel: string; format?: "count" | "percent" | "points"; sampleUnit?: "场" | "次"; context: RankingContext }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const currentRow = useRef<HTMLTableRowElement>(null);
  const titleId = useId();
  const filtersId = useId();
  const tableScroll = useRef<HTMLDivElement>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [minimumGames, setMinimumGames] = useState(0);
  const [customMinimum, setCustomMinimum] = useState("");
  const canFilterGames = format === "percent" && metricLabel !== "出场率";
  const showsRoundCounts = canFilterGames && sampleUnit === "次";
  const effectiveGames = (entry: RankingEntry) => entry.effective_game_count ?? entry.sample_count;
  const qualified = canFilterGames ? entries.filter((entry) => effectiveGames(entry) >= minimumGames) : entries;
  // 源 rank 已按精确比例分组；筛选后沿用同分组，避免浮点舍入把不同胜率合并。
  let sourceRank: number | undefined;
  let filteredRank = 0;
  const visibleEntries = qualified.map((entry, index) => {
    if (entry.rank !== sourceRank) { sourceRank = entry.rank; filteredRank = index + 1; }
    return { ...entry, rank: filteredRank };
  });
  const selectedEntry = entries.find((entry) => entry.id === context.playerId);
  const selectedExcluded = canFilterGames && selectedEntry && effectiveGames(selectedEntry) < minimumGames;
  function applyMinimumGames(value: number) {
    setMinimumGames(value);
    setCustomMinimum(value ? String(value) : "");
    if (tableScroll.current) tableScroll.current.scrollTop = 0;
  }
  const params = new URLSearchParams({ season_start: context.start, season_end: context.end });
  const displayValue = (value: number) => format === "percent" ? `${(value * 100).toFixed(1)}%` : formatNumber(value);
  if (!ranking) return <span className="metric-rank rank-unavailable">{label ? `${label} ` : ""}暂无排名</span>;
  return <div className="ranking-control">
    <button className="metric-rank" type="button" aria-haspopup="dialog" aria-label={`${metricLabel}：查看排行榜`} title={title ?? "点击查看当前范围内的排行榜"} onClick={() => {
      setFiltersOpen(false);
      dialog.current?.showModal();
      currentRow.current?.scrollIntoView({ block: "nearest" });
    }}>{label ? `${label} ` : ""}{provisional ? "暂列" : ""}第 <b>{ranking.rank}</b><span className="rank-total"> / {ranking.total}</span><span className="rank-arrow" aria-hidden="true"> ↗</span></button>
    <dialog ref={dialog} className="sample-dialog ranking-dialog" aria-labelledby={titleId} onClick={(event) => {
      if (event.target !== event.currentTarget) return;
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
    }}>
      <header className="sample-dialog-header ranking-dialog-header">
        <h2 id={titleId}>{metricLabel}排行榜</h2>
        <p className="ranking-header-meta" aria-live="polite">{context.scopeLabel} · {formatNumber(visibleEntries.length)} 位选手{canFilterGames && minimumGames > 0 ? ` · 有效场次 ≥ ${formatNumber(minimumGames)} 场` : ""}</p>
        <button className="sample-close" type="button" aria-label="关闭排行榜" onClick={() => dialog.current?.close()}>×</button>
      </header>
      {canFilterGames ? <div className="ranking-toolbar">
        <div className="ranking-game-filter" id={filtersId} hidden={!filtersOpen}>
          <div className="ranking-filter-shortcuts"><span>最低有效场次</span><div className="ranking-minimum-options" role="group" aria-label="最低有效场次">
            {[0, 5, 10, 20].map((value) => <button key={value} type="button" aria-pressed={minimumGames === value} onClick={() => applyMinimumGames(value)}>{value ? `≥ ${value} 场` : "全部"}</button>)}
          </div></div>
          <form className="ranking-custom-minimum" onSubmit={(event) => {
            event.preventDefault();
            const value = Number(customMinimum);
            if (Number.isSafeInteger(value) && value >= 0) applyMinimumGames(value);
          }}><label><span>自定义 ≥</span><input type="number" name="minimumGames" min={0} max={Number.MAX_SAFE_INTEGER} step={1} required aria-label="自定义最低有效场次" value={customMinimum} onChange={(event) => setCustomMinimum(event.target.value)} /><span>场</span></label><button type="submit">应用</button></form>
        </div>
        <button className="ranking-filter-toggle" type="button" aria-expanded={filtersOpen} aria-controls={filtersId} data-active={minimumGames > 0 || undefined} onClick={() => setFiltersOpen((value) => !value)}><span aria-hidden="true">{filtersOpen ? "›" : "‹"}</span>筛选场次</button>
      </div> : null}
      {selectedExcluded ? <p className="ranking-filter-status" role="status">当前选手有 {formatNumber(effectiveGames(selectedEntry))} 场有效对局，未达到 {formatNumber(minimumGames)} 场，暂不参与本次排名。</p> : null}
      <div ref={tableScroll} className="ranking-table-scroll"><table className="ranking-table"><thead><tr><th scope="col">排名</th><th scope="col">选手</th><th scope="col">{metricLabel}</th><th scope="col">{showsRoundCounts ? "有效场次 / 票次" : "有效样本"}</th></tr></thead><tbody>{visibleEntries.map((entry) => <tr key={entry.id} ref={entry.id === context.playerId ? currentRow : undefined} data-current={entry.id === context.playerId ? "true" : undefined}>
        <td><b>{entry.rank}</b></td><td><Link href={`/players/${encodeURIComponent(entry.id)}?${params}`} onClick={() => dialog.current?.close()}>{entry.name}</Link>{entry.id === context.playerId ? <small>当前选手</small> : null}</td><td className="ranking-value">{displayValue(entry.value)}</td><td>{showsRoundCounts ? <>{formatNumber(effectiveGames(entry))} 场<small className="ranking-round-count">{formatNumber(entry.sample_count)} 次投票</small></> : <>{formatNumber(entry.sample_count)} {sampleUnit}</>}</td>
      </tr>)}</tbody></table></div>
      {visibleEntries.length === 0 ? <p className="ranking-empty" role="status">当前条件下没有符合要求的选手，可以降低场次门槛。</p> : null}
      <p className="ranking-note">仅比较当前范围内有有效数据的选手；同分选手按姓名排列。</p>
    </dialog>
  </div>;
}
