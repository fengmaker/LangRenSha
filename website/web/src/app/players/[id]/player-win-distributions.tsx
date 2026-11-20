"use client";

import { useState } from "react";
import { MetricSamples } from "@/components/metric-samples";
import { formatNumber } from "@/lib/format";
import type { PlayerBoardStats, PlayerLedgerEntry, PlayerStats } from "@/lib/types";
import { MetricRank, type RankingContext } from "./metric-rank";
import styles from "./player-detail.module.css";

export function rateText(rate: number | null | undefined): string {
  return typeof rate === "number" && Number.isFinite(rate) ? `${(rate * 100).toFixed(1)}%` : "—";
}

type Results = Pick<PlayerBoardStats, "wins" | "losses" | "pending_games">;

function WinLoss({ wins, losses, pending_games }: Results) {
  return <span className={styles.winLoss}>
    <span>{formatNumber(wins)}&nbsp;胜 {formatNumber(losses)}&nbsp;负</span>
    {pending_games > 0 ? <small>{formatNumber(pending_games)} 场待结算</small> : null}
  </span>;
}

type IdentityGroup = "good" | "other" | "wolf";

function identityGroup(games: PlayerLedgerEntry[]): IdentityGroup {
  if (games.length && games.every(({ faction }) => faction === "good")) return "good";
  if (games.length && games.every(({ faction }) => faction === "werewolf")) return "wolf";
  return "other";
}

export function RoleWinRates({ roles, ledger, rankContext }: {
  roles: PlayerStats["roles"];
  ledger: PlayerLedgerEntry[];
  rankContext: RankingContext;
}) {
  if (!roles.length) return <p className="lane-empty">身份胜率记录尚未整理。</p>;
  const groups: Record<IdentityGroup, { role: PlayerStats["roles"][number]; games: PlayerLedgerEntry[]; group: IdentityGroup }[]> = {
    good: [], other: [], wolf: [],
  };
  for (const role of roles) {
    const games = ledger.filter((game) => (game.role || "身份未知") === role.role);
    const group = role.role === "混血儿" ? "other" : identityGroup(games);
    groups[group].push({ role, games, group });
  }

  return <table className={`${styles.distribution} ${styles.winTable}`} aria-label="身份胜率分布">
    <colgroup>
      <col className={styles.identityNameColumn} /><col />
      <col className={styles.identityRankColumn} /><col className={styles.identitySampleColumn} />
    </colgroup>
    <thead><tr>
      <th scope="col">身份</th><th scope="col">胜率</th><th scope="col">排名</th><th scope="col">样本</th>
    </tr></thead>
    <tbody>{[...groups.good, ...groups.other, ...groups.wolf].map(({ role, games, group }) => {
      const name = `${role.role}身份胜率`;
      const percentage = rateText(role.win_rate);
      return <tr key={role.role} data-profile-tone={group}>
        <th scope="row" className={styles.identityName}>{role.role}</th>
        <td><div className={styles.identityRate}>
          <strong>{percentage}</strong>
          <span className={styles.rateTrack} aria-hidden="true">
            {percentage !== "—" ? <span style={{ width: percentage }} /> : null}
          </span>
          <WinLoss {...role} />
        </div></td>
        <td><MetricRank ranking={role.ranking} entries={role.ranking_board} metricLabel={name} format="percent" context={rankContext}
          title={role.ranking ? `当前筛选范围内，与同为${role.role}且有有效胜负的 ${role.ranking.total} 位选手比较` : undefined} /></td>
        <td>{role.metric ? <MetricSamples label={name} metric={role.metric} games={games} trigger="查看"
          labels={{ positive: "获胜", negative: "失利", unit: "场", description: `仅展示当前筛选范围内，以${role.role}身份出场的对局。正面样本为胜局，负面样本为负局。` }} /> : null}</td>
      </tr>;
    })}</tbody>
  </table>;
}

type BoardSort = "appearances" | "win_rate";
type SortDirection = "ascending" | "descending";

export function BoardWinRates({ boards, ledger, rankContext }: {
  boards: PlayerBoardStats[];
  ledger: PlayerLedgerEntry[];
  rankContext: RankingContext;
}) {
  const [sort, setSort] = useState<{ field: BoardSort; direction: SortDirection }>({ field: "appearances", direction: "descending" });
  if (!boards.length) return <p className="lane-empty">版型胜率记录尚未整理。</p>;

  const ordered = boards.map((board) => ({ ...board, name: board.name || board.code || "版型待核" })).sort((a, b) => {
    const first = a[sort.field], second = b[sort.field];
    if (first === null && second !== null) return 1;
    if (second === null && first !== null) return -1;
    const difference = (first ?? 0) - (second ?? 0);
    return (sort.direction === "ascending" ? difference : -difference)
      || b.appearances - a.appearances || a.name.localeCompare(b.name, "zh-CN");
  });

  function sortHeader(field: BoardSort, label: string) {
    const direction = sort.field === field ? sort.direction : undefined;
    return <th scope="col" aria-sort={direction}>
      <button type="button" className={styles.boardSort} data-direction={direction} onClick={() =>
        setSort({ field, direction: direction === "descending" ? "ascending" : "descending" })
      }>{label}<span aria-hidden="true" /></button>
    </th>;
  }

  return <table className={`${styles.distribution} ${styles.winTable}`} aria-label="版型胜率分布">
    <colgroup>
      <col /><col className={styles.boardAppearances} /><col className={styles.boardRecord} />
      <col className={styles.boardRate} /><col className={styles.boardRank} /><col className={styles.boardSamples} />
    </colgroup>
    <thead><tr>
      <th scope="col">版型</th>{sortHeader("appearances", "出场")}
      <th scope="col" className={styles.boardRecord}>胜负</th>{sortHeader("win_rate", "胜率")}
      <th scope="col">名次</th><th scope="col">样本</th>
    </tr></thead>
    <tbody>{ordered.map((board) => {
      const name = `${board.name}版型胜率`;
      const gameIds = new Set(board.metric.game_ids);
      return <tr key={board.code || board.name} data-board-code={board.code || undefined}>
        <th scope="row">{board.name}</th>
        <td>{formatNumber(board.appearances)}</td>
        <td className={styles.boardRecord}><WinLoss {...board} /></td>
        <td><strong>{rateText(board.win_rate)}</strong><div className={styles.narrowRecord}><WinLoss {...board} /></div></td>
        <td><MetricRank ranking={board.ranking} entries={board.ranking_board} metricLabel={name} format="percent" context={rankContext}
          title={board.ranking ? `当前筛选范围内，与同样参加${board.name}且有有效胜负的 ${board.ranking.total} 位选手比较` : undefined} /></td>
        <td><MetricSamples label={name} metric={board.metric} games={ledger.filter((game) => gameIds.has(game.game_id))} trigger="查看"
          labels={{ positive: "获胜", negative: "失利", unit: "场", description: `仅展示当前筛选范围内，参加${board.name}版型的对局。正面样本为胜局，负面样本为负局。` }} /></td>
      </tr>;
    })}</tbody>
  </table>;
}
