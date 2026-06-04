import type { ClipReviewEvent } from "@/types/events";

const SESSION_ID = "GS_MOCK_001";
const BASE_TIME = Date.parse("2026-05-25T12:00:00Z");

function ev(
  id: number,
  offsetSec: number,
  stage: string,
  decision: string,
  extra: Partial<ClipReviewEvent> = {},
): ClipReviewEvent {
  return {
    id,
    session_id: SESSION_ID,
    stage,
    decision,
    clip_index: null,
    comment: "",
    hints: null,
    event_metadata: null,
    created_at: new Date(BASE_TIME + offsetSec * 1000).toISOString(),
    ...extra,
  };
}

export const MOCK_EVENTS: ClipReviewEvent[] = [
  ev(1, 0, "session", "created", { comment: "谷歌I/O大会" }),
  ev(2, 5, "character", "locked", { comment: "su_wan" }),
  ev(3, 8, "storyboard", "locked", { comment: "MOCK001" }),
  ev(4, 180, "clip", "continue", { clip_index: 1, event_metadata: { duration_sec: 5 } }),
  ev(5, 360, "clip", "continue", { clip_index: 2, event_metadata: { duration_sec: 5 } }),
  ev(6, 540, "clip", "regen", {
    clip_index: 3,
    comment: "人物近 + 不要文字",
    hints: ["closer_shot", "no_text"],
    event_metadata: { regen_count: 1 },
  }),
  ev(7, 660, "clip", "regen", {
    clip_index: 3,
    comment: "再近一点",
    hints: ["closer_shot"],
    event_metadata: { regen_count: 2 },
  }),
  ev(8, 840, "clip", "continue", { clip_index: 4, event_metadata: { duration_sec: 10 } }),
  ev(9, 1020, "final", "failed", { comment: "clip 5 kling 超时" }),
  ev(10, 1025, "session", "failed", { comment: "因 clip 5 失败终止" }),
];

export function getMockEvents(sessionId: string): ClipReviewEvent[] {
  if (sessionId === SESSION_ID || sessionId === "MOCK001") return MOCK_EVENTS;
  return [];
}
