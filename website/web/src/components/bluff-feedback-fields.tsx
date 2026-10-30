import type { BluffReview } from "@/lib/types";
import { gamePhaseLabel } from "@/lib/format";

export function BluffFeedbackFields({ item }: { item: BluffReview["items"][number] }) {
  const prefix = `feedback-${item.bvid}-${item.seat}`;
  return <form className="bluff-feedback-form" aria-label={`复核 ${item.name} ${item.review_id}`}
    data-review-id={item.review_id} data-game-id={item.game_id} data-bvid={item.bvid ?? ""}
    data-seat={item.seat} data-name={item.name} data-physical-role={item.physical_role}
    data-fingerprint={item.claim_fingerprint ?? item.source_fingerprint} data-source-fingerprint={item.source_fingerprint}
    data-success-fingerprint={item.success_fingerprint ?? ""}>
    <h3>填写本条复核意见</h3>
    <div className="bluff-feedback-choices">
      <label htmlFor={`${prefix}-decision`}>复核结论<select id={`${prefix}-decision`} name="decision" defaultValue="">
        <option value="">尚未填写</option><option value="yes">确认是悍跳</option><option value="no">确认不是悍跳</option><option value="later">仅后续天数起跳，请再核查</option><option value="uncertain">仍无法确定</option><option value="comment">有其他意见</option>
      </select></label>
      <label htmlFor={`${prefix}-day`}>发生天数<select id={`${prefix}-day`} name="claim_day" defaultValue={item.claim_day == null ? "" : String(item.claim_day)}>
        <option value="">尚未确定</option><option value="1">{gamePhaseLabel(1, "day")}</option><option value="2">{gamePhaseLabel(2, "day")}（含延期竞选）</option><option value="later">后续天数，请见意见</option>
      </select></label>
      <label htmlFor={`${prefix}-role`}>所跳身份<select id={`${prefix}-role`} name="claimed_role" defaultValue={item.claimed_role ?? ""}>
        <option value="">待定／不适用</option><option value="预言家">预言家</option><option value="通灵师">通灵师</option>
      </select></label>
    </div>
    {item.decision === "yes" && !item.claim_needs_review ? <label htmlFor={`${prefix}-success`}>悍跳成功结论（可选）<select id={`${prefix}-success`} name="manual_success" defaultValue="">
      <option value="">尚未复核</option><option value="yes">确认成功</option><option value="no">确认失败</option><option value="unknown">保留待定</option>
    </select></label> : null}
    <label htmlFor={`${prefix}-notes`}>其他意见<textarea id={`${prefix}-notes`} name="notes" rows={3} maxLength={4000} placeholder="可填写正确座位、首日时间点、所跳身份或不同意见。" /></label>
    <p data-feedback-row-status>尚未填写</p>
  </form>;
}
