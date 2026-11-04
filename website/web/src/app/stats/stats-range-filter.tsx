"use client";

import { useEffect, useState, type FormEvent } from "react";
import styles from "./stats.module.css";
import { publicPath } from "@/lib/site-mode";

export function StatsRangeFilter({ seasons, start, end, onApply }: { seasons: string[]; start: string; end: string; onApply?: (start: string, end: string) => void }) {
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);

  useEffect(() => { setFrom(start); setTo(end); }, [start, end]);

  function changeStart(value: string) {
    setFrom(value);
    if (to !== "latest" && seasons.indexOf(to) < seasons.indexOf(value)) setTo(value);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    if (!onApply) return;
    event.preventDefault();
    onApply(from, to);
  }

  return (
    <form method="get" action={publicPath("/stats")} className={styles.rangeForm} aria-label="筛选统计范围" onSubmit={submit}>
      <label className="filter-field">
        <span>起始赛季</span>
        <select name="season_start" value={from} onChange={(event) => changeStart(event.target.value)}>
          {seasons.map((season) => <option key={season} value={season}>{season}</option>)}
        </select>
      </label>
      <span className={styles.rangeDivider} aria-hidden="true">—</span>
      <label className="filter-field">
        <span>结束赛季</span>
        <select name="season_end" value={to} onChange={(event) => setTo(event.target.value)}>
          <option value="latest">至今</option>
          {seasons.map((season, index) => <option key={season} value={season} disabled={index < seasons.indexOf(from)}>{season}</option>)}
        </select>
      </label>
      <button className="button button-primary" type="submit">查看统计 <span aria-hidden="true">→</span></button>
    </form>
  );
}
