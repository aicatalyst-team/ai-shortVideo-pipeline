export interface ClipNodePreview {
  first_frame_url: string;
  video_url: string;
  tail_frame_url: string;
}

export interface ClipNodeText {
  narration_segment: string;
  visual_prompt: string;
  kling_prompt: string;
  character_id: string | null;
  environment_id: string | null;
}

export interface ClipNodeTimeline {
  target_video_sec: number;
  actual_video_sec: number;
  est_tts_sec: number;
  drift_sec: number;
}

export interface ClipNodeReview {
  status: string;
  regen_count: number;
  locked_at: string | null;
  dirty_reason: string;
  last_hints: string[];
}

export interface ClipNodeOps {
  can_continue: boolean;
  can_regenerate: boolean;
  can_replace_first_frame: boolean;
  can_replace_tail_frame: boolean;
  can_edit_prompt: boolean;
  can_cancel: boolean;
}

export interface ClipNodeCost {
  clip_cny: number;
  regen_count: number;
  regen_total_cny: number;
  cost_breakdown: Record<string, number>;
  risk_warning: string;
}

export interface ClipNodeDependencies {
  depends_on: number[];
  blocking_for: number[];
  chain_from_tail: boolean;
}

export interface ClipNodeData {
  clip_id: string;
  seq: number;
  preview: ClipNodePreview;
  text: ClipNodeText;
  timeline: ClipNodeTimeline;
  review: ClipNodeReview;
  ops: ClipNodeOps;
  cost: ClipNodeCost;
  dependencies: ClipNodeDependencies;
}

export interface CostSummary {
  clip_count: number;
  session_total_cny: number;
  regen_total_cny: number;
  est_remaining_cny: number;
  cost_per_clip_avg: number;
  warnings: string[];
}
