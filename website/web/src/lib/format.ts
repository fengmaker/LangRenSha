export function formatNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("zh-CN").format(value) : "—";
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "日期待核";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function phaseLabel(value: string | null | undefined): string {
  if (!value) return "阶段待核";
  const labels: Record<string, string> = { regular: "正赛", finals_week: "决赛周", qualifier: "资格赛", promotion: "晋级赛", special: "特别场", exhibition: "表演赛" };
  return labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "其他阶段");
}

export function winnerLabel(value: string | null | undefined): string {
  if (value === "good") return "好人胜";
  if (value === "werewolf") return "狼人胜";
  if (value === "good_win") return "好人胜";
  if (value === "werewolf_win") return "狼人胜";
  if (value === "draw") return "平局";
  if (value === "unknown" || value == null || value === "") return "结果未知";
  return /[\u4e00-\u9fff]/.test(value) ? value : "结果未知";
}

export function factionLabel(value: string | null | undefined): string {
  if (value === "good") return "好人阵营";
  if (value === "werewolf") return "狼人阵营";
  if (value === "third_party") return "第三方";
  if (value === "unknown" || value == null || value === "") return "阵营未知";
  return /[\u4e00-\u9fff]/.test(value) ? value : "阵营未知";
}

export function actionLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    unknown: "未知",
    pass: "未发动",
    not_applicable: "不适用",
    choose: "选择",
    exchange: "交换",
    dream: "梦魇",
    wolf: "狼人行动",
    good: "好人行动",
    dance: "舞蹈",
    give_mask: "赠送面具",
    verify: "验证",
    select: "选择",
    no_death: "无人出局",
    attempt: "尝试发动",
    clear: "清除",
    clear_mark: "清除标记",
    mark: "施加标记",
    destroy: "撕毁警徽",
    disqualify: "DQ出局",
    invalidated_by_dq: "行动因DQ失效",
    hold: "保留",
    hunt: "发动猎杀时刻",
    kill: "猎杀",
    speak: "发言",
    surrender: "交牌",
    swap: "交换",
    vote: "投票",
    select_pair: "选择对象",
    trade: "交易",
    cancelled: "已取消",
    not_triggered: "未触发",
    continued: "继续",
    immune: "免疫",
    guard: "守卫",
    register: "登记",
    not_held: "未举行",
    deferred: "延期",
    unavailable: "不可用",
    not_carrying: "未携带",
    learn: "学习",
    order: "顺序",
    self_destruct: "自爆",
    can_shoot: "可开枪",
    cannot_shoot: "不能开枪",
    attack: "击杀",
    badge_lost: "警徽流失",
    save: "救人",
    poison: "毒杀",
    check: "查验",
    shoot: "开枪",
    elected: "当选",
    peaceful: "平安夜",
    die: "出局",
    exile: "放逐",
    none: "无",
    transfer: "移交",
    revoke: "撕毁",
    reveal: "翻牌",
    forbidden: "规则禁止",
    no_skill: "无此技能",
    skill_disabled: "技能失效",
    invalid_exchange: "交换无效",
    warden_self_trade: "典狱长自身交易",
    die_after_speech: "发言后出局",
    minority_dies: "少数派淘汰",
  };
  if (!value) return "未知";
  return labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "其他动作");
}

export function voteStatusLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    complete: "记录完整",
    partial: "部分记录",
    incomplete: "记录不完整",
    interrupted: "中断",
    delayed: "延期",
    unknown: "未知",
    not_applicable: "不适用",
    recorded: "已记录",
    absent: "缺席",
    deferred: "延期",
    badge_lost: "流徽",
    interrupted_self_destruct: "自爆中断",
    not_held: "未举行",
    game_ended: "对局结束",
  };
  return value ? labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "状态未知") : "未知";
}

export function availabilityLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    available: "可用",
    no_living_wolves: "已无存活狼人",
    dead: "已出局",
    wrong_phase: "当前阶段不可用",
    wolves_alive: "其他狼人仍在场",
    learning: "学习当夜不可用",
    not_applicable: "不适用",
    unknown: "适用情况未知",
    guard: "守卫",
    register: "登记",
    not_held: "未举行",
    deferred: "延期",
    unavailable: "不可用",
    not_carrying: "未携带",
    learn: "学习",
    order: "顺序",
    self_destruct: "自爆",
    can_shoot: "可开枪",
  };
  if (!value) return "未知";
  return labels[value] ?? (/[\u4e00-\u9fff]/.test(value) ? value : "状态未知");
}
