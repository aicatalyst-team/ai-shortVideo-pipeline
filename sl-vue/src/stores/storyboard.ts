import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { fetchStoryboard } from "@/api/storyboard";
import type { StoryboardDbResponse } from "@/types/storyboard";

export const useStoryboardStore = defineStore("storyboard", () => {
  const current = ref<StoryboardDbResponse | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const lastLoadedPlanId = ref<string | null>(null);

  const clipNodes = computed(() => current.value?.clip_nodes ?? []);
  const costSummary = computed(() => current.value?.cost_summary ?? null);
  const title = computed(() => current.value?.title ?? "");

  async function load(planId: string, includeFrames = false): Promise<void> {
    loading.value = true;
    error.value = null;
    lastLoadedPlanId.value = planId;
    try {
      current.value = await fetchStoryboard(planId, includeFrames);
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
      current.value = null;
    } finally {
      loading.value = false;
    }
  }

  function clear(): void {
    current.value = null;
    error.value = null;
    lastLoadedPlanId.value = null;
  }

  async function refreshClip(_clipId: string): Promise<void> {
    if (!lastLoadedPlanId.value) return;
    await load(lastLoadedPlanId.value, true);
  }

  function markDirty(clipId: string): void {
    const clip = current.value?.clip_nodes.find((item) => item.clip_id === clipId);
    if (!clip) return;
    clip.review.status = "dirty";
    clip.review.dirty_reason = "上游片段已重生成";
  }

  return {
    current,
    loading,
    error,
    clipNodes,
    costSummary,
    title,
    load,
    clear,
    refreshClip,
    markDirty,
  };
});
