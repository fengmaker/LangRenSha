import { formatDate, formatNumber } from "@/lib/format";
import styles from "./data-scope-summary.module.css";

export function DataScopeSummary({ range, gameCount, gameCountLabel = "对局总数", latestDate, note }: {
  range: string;
  gameCount: number;
  gameCountLabel?: string;
  latestDate?: string | null;
  note?: string;
}) {
  return <section className={styles.summary} aria-label="统计范围">
    <dl>
      <div><dt>统计范围</dt><dd>{range}</dd></div>
      <div><dt>{gameCountLabel}</dt><dd>{formatNumber(gameCount)} 局</dd></div>
      {latestDate ? <div><dt>最新对局日期</dt><dd><time dateTime={latestDate}>{formatDate(latestDate)}</time></dd></div> : null}
    </dl>
    {note ? <p className={styles.note}>{note}</p> : null}
  </section>;
}
