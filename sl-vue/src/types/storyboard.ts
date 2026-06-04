import type { ClipNodeData, CostSummary } from "./clip_node";

export interface ClipResponse {
  id: string;
  seq: number;
  prompt: string;
  narration_segment: string;
  duration_sec: number;
  video_url: string;
  status: string;
  r_metadata?: Record<string, unknown> | null;
}

export interface FrameAssetResponse {
  id: string;
  clip_id: string | null;
  kind: string;
  url: string;
  width: number;
  height: number;
}

export interface StoryboardDbResponse {
  id: string;
  plan_id: string | null;
  title: string;
  theme: string;
  style_name: string;
  status: string;
  metadata?: Record<string, unknown> | null;
  clips: ClipResponse[];
  frames: FrameAssetResponse[];
  clip_nodes: ClipNodeData[];
  cost_summary: CostSummary | null;
  source: string;
}
