"use client";

import { useId, useState } from "react";

export function SeasonRangeFilter({ action, seasons, start, end, minimumAppearances }: {
  action: string; seasons: string[]; start: string; end: string; minimumAppearances: number;
}) {
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);
  const [filterOpen, setFilterOpen] = useState(false);
  const [minimum, setMinimum] = useState(String(minimumAppearances));
  const filterId = useId();
  function changeStart(value: string) {
    setFrom(value);
    if (to !== "latest" && seasons.indexOf(to) < seasons.indexOf(value)) setTo(value);
  }
  return <form method="get" action={action} className="profile-range-controls" aria-label="筛选赛季范围与排名出场次数">
    <div className="profile-filter-form">
    <label className="filter-field"><span>起始赛季</span><select name="season_start" value={from} onChange={(event) => changeStart(event.target.value)}>{seasons.map((season) => <option key={season} value={season}>{season}</option>)}</select></label>
    <span className="range-divider" aria-hidden="true">—</span>
    <label className="filter-field"><span>结束赛季</span><select name="season_end" value={to} onChange={(event) => setTo(event.target.value)}><option value="latest">至今</option>{seasons.map((season, index) => <option key={season} value={season} disabled={index < seasons.indexOf(from)}>{season}</option>)}</select></label>
    <button className="button button-primary" type="submit">查看表现 <span>→</span></button>
    </div>
    <div className="profile-appearance-toolbar">
      <button className="profile-appearance-toggle" type="button" aria-expanded={filterOpen} aria-controls={filterId}
        data-active={minimumAppearances > 0 || undefined} onClick={() => setFilterOpen((value) => !value)}>
        筛选出场次数
        <small>{minimumAppearances ? `≥ ${minimumAppearances} 场` : "全部"}</small>
        <span aria-hidden="true">{filterOpen ? "‹" : "›"}</span>
      </button>
    <div id={filterId} className="profile-appearance-options" role="group" aria-label="最低出场次数" hidden={!filterOpen}>
      <div className="profile-appearance-shortcuts">
        {[0, 5, 10, 20].map((value) => <button type="button" key={value} aria-pressed={minimum === String(value)}
          onClick={() => setMinimum(String(value))}>{value ? `≥ ${value} 场` : "全部"}</button>)}
      </div>
      <label>自定义 ≥ <input type="number" name="minimum_appearances" min={0} max={Number.MAX_SAFE_INTEGER} step={1} required
        aria-label="区间最低出场次数" value={minimum} onChange={(event) => setMinimum(event.target.value)} /><span>场</span></label>
      <button className="button button-primary" type="submit">应用筛选</button>
    </div>
    </div>
  </form>;
}
