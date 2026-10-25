"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export function LeaderboardScroll({ children, heading }: { children: ReactNode; heading: ReactNode }) {
  const tableId = useId();
  const tableScroll = useRef<HTMLDivElement>(null);
  const headerScroll = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState(0);
  const [maxScroll, setMaxScroll] = useState(0);

  useEffect(() => {
    const table = tableScroll.current;
    if (!table) return;

    const updateTrack = () => {
      setMaxScroll(Math.max(0, table.scrollWidth - table.clientWidth));
      setPosition(table.scrollLeft);
      if (headerScroll.current) headerScroll.current.scrollLeft = table.scrollLeft;
    };
    updateTrack();
    const observer = new ResizeObserver(updateTrack);
    observer.observe(table);
    if (table.firstElementChild) observer.observe(table.firstElementChild);
    return () => observer.disconnect();
  }, [children]);

  function dragTo(next: number) {
    if (tableScroll.current) tableScroll.current.scrollLeft = next;
    syncPosition(next);
  }

  function syncPosition(next: number) {
    setPosition(next);
    if (headerScroll.current) headerScroll.current.scrollLeft = next;
  }

  function move(direction: number) {
    const table = tableScroll.current;
    if (table) table.scrollBy({ left: direction * Math.max(240, table.clientWidth * 0.75), behavior: "smooth" });
  }

  return <div className="leaderboard-scroll-shell">
    <div ref={headerScroll} className="leaderboard-pinned-header" aria-hidden="true"><table className="leaderboard-table leaderboard-comparison">{heading}</table></div>
    <div id={tableId} ref={tableScroll} className="data-table-scroll leaderboard-scroll" role="region" aria-label="选手积分与统计，可横向滚动" tabIndex={0} onScroll={(event) => syncPosition(event.currentTarget.scrollLeft)}>{children}</div>
    <div className="leaderboard-scroll-toolbar" role="group" aria-label="横向查看积分榜字段">
      <span>左右查看字段</span>
      <button type="button" onClick={() => move(-1)} aria-label="向左滚动积分榜" aria-controls={tableId}>←</button>
      <input type="range" className="leaderboard-bottom-scroll" min={0} max={Math.max(1, maxScroll)} step={1} value={Math.min(position, maxScroll)} disabled={!maxScroll} aria-label="积分榜底部横向滚动条" aria-controls={tableId} aria-valuetext={position <= 0 ? "最左侧" : position >= maxScroll ? "最右侧" : `已横向滚动 ${Math.round(position / maxScroll * 100)}%`} onChange={(event) => dragTo(Number(event.currentTarget.value))} />
      <button type="button" onClick={() => move(1)} aria-label="向右滚动积分榜" aria-controls={tableId}>→</button>
    </div>
  </div>;
}
