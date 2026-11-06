export function MetricFormula({ numerator, denominator, percent = false }: {
  numerator: string | number; denominator: string | number; percent?: boolean;
}) {
  return <span className="metric-formula" role="math" aria-label={`${numerator} 除以 ${denominator}${percent ? "，乘以 100%" : ""}`}>
    <span className="metric-fraction" aria-hidden="true"><span>{numerator}</span><span>{denominator}</span></span>
    {percent ? <span className="metric-factor" aria-hidden="true"><span className="metric-operator">×</span><span>100%</span></span> : null}
  </span>;
}
