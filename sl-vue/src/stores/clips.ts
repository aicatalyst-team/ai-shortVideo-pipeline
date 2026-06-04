import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { useStoryboardStore } from "./storyboard";
import type { ClipNodeData } from "@/types/clip_node";

export const useClipsStore = defineStore("clips", () => {
  const selectedClipId = ref<string | null>(null);
  const storyboardStore = useStoryboardStore();

  const selectedClip = computed<ClipNodeData | null>(() => {
    if (!selectedClipId.value) return null;
    return storyboardStore.clipNodes.find((clip) => clip.clip_id === selectedClipId.value) ?? null;
  });

  function select(clipId: string | null): void {
    selectedClipId.value = clipId;
  }

  return { selectedClipId, selectedClip, select };
});
