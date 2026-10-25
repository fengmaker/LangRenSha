import type { Leaderboard } from "@/lib/types";

type Rule = {
  field: string;
  calculation: string;
  note: string;
};

export function LeaderboardCalculationRules({
  scoring,
}: {
  scoring: Leaderboard["scoring"];
}) {
  const rules: Rule[] = [
    {
      field: "名次",
      calculation: "按当前榜单积分从高到低排序",
      note: "积分相同的选手并列。",
    },
    {
      field: "选手",
      calculation: "选手资料中登记的姓名",
      note: "点击姓名查看个人主页。",
    },
    {
      field: "积分",
      calculation: `狼人胜场 × ${scoring.werewolf_win} + 好人胜场 × ${scoring.good_win} + 个人负场 × (${scoring.loss})`,
      note: "按个人胜利阵营与整局胜方判定；胜负或阵营待核的对局暂不计入已知积分。",
    },
    {
      field: "整季出场",
      calculation: "选手有出场记录的整季正式对局数",
      note: "",
    },
    {
      field: "出场率",
      calculation: "整季出场次数 ÷ 整季正式对局总数 × 100%",
      note: "",
    },
    {
      field: "总胜场",
      calculation: "个人胜利场次（好人胜场 + 狼人胜场）",
      note: "个人胜利阵营与整局胜方一致时计为胜场。",
    },
    {
      field: "整季胜率",
      calculation: "整季个人胜场 ÷ 已结算的个人胜负场次 × 100%",
      note: "胜负或个人阵营待定的对局不进入分母。",
    },
    {
      field: "上警率",
      calculation: "首次报名上警次数 ÷ 上警名单明确的整季出场次数 × 100%",
      note: "每局只看首次报名；名单缺失的出场不纳入分母，延期竞选不重复计数。",
    },
    {
      field: "投狼次数",
      calculation: "投向狼人阵营的好人放逐票数",
      note: "仅计票权名单明确有票权的好人放逐票；包含预言家、通灵师及PK和技能复投。明确弃票算失败，缺失投票或目标阵营未知排除。",
    },
    {
      field: "投狼率",
      calculation: "投向狼人阵营的好人放逐票数 ÷ 可判定的好人放逐票数 × 100%",
      note: "逐轮计入PK和技能复投；明确弃票算失败，缺失投票或目标阵营未知予以排除。",
    },
    {
      field: "放逐弃票",
      calculation: "好人阵营放逐轮次中明确登记的弃票次数",
      note: "包括按规则登记的默认弃票；明确无票权者排除，票权名单缺失时仍计明确弃票。没有投票记录不会补记为弃票。",
    },
    {
      field: "好人胜场",
      calculation: "个人胜利阵营为好人且该局胜出的场次",
      note: "按个人胜利阵营统计。",
    },
    {
      field: "好人胜率",
      calculation: "好人胜场 ÷ 已结算的好人阵营场次 × 100%",
      note: "胜方或个人阵营待定的场次不进入分母。",
    },
    {
      field: "警徽正确率",
      calculation: "投给唯一预言家或通灵师的好人警徽票 ÷ 可判定的警徽票 × 100%",
      note: "统计有票权的好人（预言家本人除外），且信息神为合法候选的轮次；PK和技能复投逐轮计入，弃票算失败，缺失记录排除。",
    },
    {
      field: "好人站边率",
      calculation: "与唯一预言家或通灵师投向相同的好人放逐票 ÷ 可判定的站边票 × 100%",
      note: "统计有票权且非预言家或通灵师的好人，双方须同轮有票权；PK和技能复投逐轮计入。信息神弃票时该轮不计，本人弃票算失败，缺失记录排除。",
    },
    {
      field: "狼人场次",
      calculation: "个人胜利阵营为狼人的整季出场次数",
      note: "未知阵营不计作狼人。",
    },
    {
      field: "拿狼率",
      calculation: "狼人阵营出场次数 ÷ 个人胜利阵营已知的整季出场次数 × 100%",
      note: "个人胜利阵营未知的场次不纳入分母。",
    },
    {
      field: "自爆率",
      calculation: "有明确主动自爆记录的狼人场次 ÷ 狼人场次 × 100%",
      note: "按选手每局最多计一次；被放逐、淘汰或技能带走不算自爆。",
    },
    {
      field: "狼人上警率",
      calculation: "首次报名上警的狼人次数 ÷ 上警名单明确的狼人场次 × 100%",
      note: "按个人胜利阵营统计，每局只看首次报名；名单缺失或无法确认上警名单时排除。",
    },
    {
      field: "狼人胜场",
      calculation: "个人胜利阵营为狼人且该局胜出的场次",
      note: "按个人胜利阵营统计。",
    },
    {
      field: "狼人胜率",
      calculation: "狼人胜场 ÷ 已结算的狼人阵营场次 × 100%",
      note: "胜方或个人阵营待定的场次不进入分母。",
    },
    {
      field: "悍跳次数",
      calculation: "已识别的悍跳次数",
      note: "须为狼人底牌公开自称预言家或通灵师；同一玩家同一局最多计一次。好人诈身份、仅计划起跳或跳其他身份不计。盗宝通灵等特殊位置按逐局复核结论判定；用户确认与推断分别标明。",
    },
    {
      field: "悍跳成功率",
      calculation: "成功次数 ÷ 成功结果可判定的悍跳次数 × 100%",
      note: "该悍跳者竞选拿徽，或首日起跳且首日最终放逐好人，任一成立即成功；延期竞选不把次日放逐算作首日。结果不明时排除。",
    },
    {
      field: "技能正确率",
      calculation: "—",
      note: "暂未制定统计口径。",
    },
    {
      field: "狼人技能正确率",
      calculation: "—",
      note: "暂未制定统计口径。",
    },
    {
      field: "好人技能正确率",
      calculation: "—",
      note: "暂未制定统计口径。",
    },
  ];

  return (
    <details
      id="leaderboard-calculation-rules"
      className="leaderboard-calculation-rules"
    >
      <summary>指标计算规则</summary>
      <p>
        积分按当前榜单范围累计：整季榜包含决赛周，决赛周冠军榜只计决赛周；其余指标均统计整季。
        比例按分子 ÷ 分母 × 100% 计算，分母为零时显示“—”；单元格明细中的数字按“分子 / 分母”排列。
        好人、狼人分类按个人胜利阵营统计，混血儿跟随其榜样；悍跳另须满足狼人底牌。
      </p>
      <div className="leaderboard-rules-scroll">
        <table
          className="leaderboard-rules-table"
          aria-label="积分榜各字段的计算方式与统计说明"
        >
          <thead>
            <tr>
              <th scope="col">字段</th>
              <th scope="col">计算方式</th>
              <th scope="col">统计说明</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.field}>
                <th scope="row">{rule.field}</th>
                <td>{rule.calculation}</td>
                <td>{rule.note || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
