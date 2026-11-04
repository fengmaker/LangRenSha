import type { BluffReview } from "@/lib/types";

export function filterBluffReview(data: BluffReview, status: BluffReview["status"], player = ""): BluffReview {
  const scopedItems = data.items.filter((item) => !player || item.player_id === player);
  const items = scopedItems.filter((item) => status === "all"
    || (status === "assistant_pending" ? item.assistant_pending : item.requires_user_review));
  const identified = scopedItems.filter((item) => item.decision === "yes");
  return {
    ...data,
    status,
    player,
    summary: {
      ...data.summary,
      wolf_appearances: scopedItems.filter((item) => !item.manual_included).length,
      manual_included_appearances: scopedItems.filter((item) => item.manual_included).length,
      identified_bluffs: identified.length,
      successes: identified.filter((item) => item.success === true).length,
      pending: scopedItems.filter((item) => item.requires_user_review).length,
      assistant_pending: scopedItems.filter((item) => item.assistant_pending).length,
    },
    items,
  };
}
