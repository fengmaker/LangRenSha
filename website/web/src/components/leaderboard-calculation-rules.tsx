import type { ReactNode } from "react";
import type { Leaderboard } from "@/lib/types";
import { MetricFormula } from "@/components/metric-formula";

type Rule = { field: string; calculation: ReactNode; note?: string };

function rate(numerator: string, denominator: string) {
  return <MetricFormula numerator={numerator} denominator={denominator} percent />;
}

export function LeaderboardCalculationRules({ scoring }: { scoring: Leaderboard["scoring"] }) {
  const rules: Rule[] = [
    { field: "名次", calculation: "按当前榜单积分从高到低排序", note: "同分并列。" },
    {
      field: "积分",
      calculation: <span className="metric-sum">
        <span className="metric-term">狼人胜场 <span className="metric-operator">×</span> {scoring.werewolf_win}</span>
        <span className="metric-term"><span className="metric-operator">+</span> 好人胜场 <span className="metric-operator">×</span> {scoring.good_win}</span>
        <span className="metric-term"><span className="metric-operator">{scoring.loss < 0 ? "−" : "+"}</span> 个人负场 <span className="metric-operator">×</span> {Math.abs(scoring.loss)}</span>
      </span>,
      note: "按当前榜单范围累计；阵营或胜负待定的出场暂不计分。",
    },
    { field: "整季出场", calculation: "选手整季参与的正式对局数" },
    { field: "出场率", calculation: rate("整季出场次数", "整季正式对局数") },
    { field: "总胜场", calculation: "好人胜场与狼人胜场之和", note: "个人胜利阵营与整局胜方一致时计为胜场。" },
    { field: "整季胜率", calculation: rate("个人胜场", "已结算出场次数"), note: "阵营或胜负待定的场次排除。" },
    { field: "上警率", calculation: rate("首次报名上警次数", "上警名单已知的出场次数"), note: "每局按首次报名计一次；延期竞选不重复计数。" },
    { field: "好人胜场", calculation: "好人阵营获胜场次" },
    { field: "好人胜率", calculation: rate("好人胜场", "已结算好人场次"), note: "阵营或胜负待定的场次排除。" },
    { field: "投狼次数", calculation: "好人放逐票中投向狼人的票数", note: "仅计已确认有票权的好人选票。" },
    { field: "投狼率", calculation: rate("投狼次数", "可判定好人放逐票数"), note: "明确弃票计入分母；投向缺失或目标阵营未知的选票排除。" },
    { field: "放逐弃票", calculation: "好人放逐票中明确记录的弃票数", note: "包含规则默认弃票；无票权者排除，票权不明时仍计明确弃票；缺失选票不补记。" },
    { field: "好人上警率", calculation: rate("好人首次报名上警次数", "报名位置已知的好人场次"), note: "阵营或首次报名名单未知时排除。" },
    { field: "好人警下率", calculation: rate("好人首次报名警下次数", "报名位置已知的好人场次"), note: "退水不计警下；每局按首次报名计一次。" },
    {
      field: "警徽正确率",
      calculation: rate("投给信息神的好人警徽票数", "可判定好人警徽票数"),
      note: "仅计有票权的好人（预言家本人除外）；唯一预言家或通灵师须为合法候选。弃票计入分母。",
    },
    {
      field: "好人站边率",
      calculation: rate("与信息神同投向的票数", "可判定好人站边票数"),
      note: "排除预言家、通灵师本人；双方同轮须有票权。信息神弃票时该轮不计，本人弃票计入分母。",
    },
    { field: "狼人场次", calculation: "狼人阵营出场次数" },
    { field: "狼人胜场", calculation: "狼人阵营获胜场次" },
    { field: "狼人胜率", calculation: rate("狼人胜场", "已结算狼人场次"), note: "阵营或胜负待定的场次排除。" },
    { field: "拿狼率", calculation: rate("狼人阵营出场次数", "个人阵营已知的出场次数"), note: "个人阵营待定的场次排除。" },
    { field: "自爆率", calculation: rate("主动自爆的狼人场次", "狼人阵营出场次数"), note: "每位选手每局最多计一次；放逐或技能淘汰不计自爆。" },
    { field: "狼人上警率", calculation: rate("狼人首次报名上警次数", "上警名单已知的狼人场次"), note: "每局按首次报名计一次。" },
    { field: "悍跳次数", calculation: "逐局复核识别的悍跳次数", note: "同一选手每局最多计一次。" },
    { field: "悍跳率", calculation: rate("悍跳次数", "可判定的狼人场次"), note: "按逐局复核范围统计；悍跳归属或阵营待定的场次排除。" },
    {
      field: "悍跳成功率",
      calculation: rate("复核成功的悍跳次数", "结果已确定的悍跳次数"),
      note: "以抗推预言家的复核结论为准；仅获得警徽不计成功。待定结果排除。",
    },
  ];

  return <details id="leaderboard-calculation-rules" className="leaderboard-calculation-rules">
    <summary>指标计算规则</summary>
    <p>积分按当前榜单范围累计：整季榜包含决赛周，决赛周冠军榜只计决赛周；其余指标均按整季统计。好人、狼人按个人胜利阵营归类。</p>
    <p>分式上方为分子、下方为分母；分母为零时比例显示“—”。投票指标按轮次计数，PK、技能复投分别计入。</p>
    <div className="leaderboard-rules-scroll">
      <table className="leaderboard-rules-table" aria-label="积分榜指标的计算公式与计数范围">
        <thead><tr><th scope="col">指标</th><th scope="col">计算公式</th><th scope="col">计数范围与排除项</th></tr></thead>
        <tbody>{rules.map((rule) => <tr key={rule.field}>
          <th scope="row">{rule.field}</th>
          <td data-label="计算公式">{rule.calculation}</td>
          <td data-label="计数范围与排除项">{rule.note || "—"}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>;
}
