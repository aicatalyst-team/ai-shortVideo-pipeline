export interface ClipReviewEvent {
  id: number;
  session_id: string;
  stage: string;
  decision: string;
  clip_index: number | null;
  comment: string;
  hints: string[] | null;
  event_metadata: Record<string, unknown> | null;
  created_at: string;
}
