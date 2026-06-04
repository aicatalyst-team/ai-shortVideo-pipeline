import client from "./client";
import { getMockStoryboard } from "@/fixtures/storyboard_mock";
import type { StoryboardDbResponse } from "@/types/storyboard";

const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

export async function fetchStoryboard(
  planId: string,
  includeFrames = false,
): Promise<StoryboardDbResponse> {
  if (USE_MOCK) {
    const mock = getMockStoryboard(planId);
    if (mock) {
      console.info(`[api/mock] fetchStoryboard(${planId}) -> mock fixture`);
      return new Promise((resolve) => setTimeout(() => resolve(mock), 200));
    }
  }
  const resp = await client.get<StoryboardDbResponse>(
    `/api/v1/storyboards/${encodeURIComponent(planId)}`,
    { params: { include_frames: includeFrames } },
  );
  return resp.data;
}
