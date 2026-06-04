<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { VueFlow, type Edge, type Node } from "@vue-flow/core";
import { useStoryboardStore } from "@/stores/storyboard";
import { useEventsStore } from "@/stores/events";
import ClipFlowNode from "@/components/canvas/ClipFlowNode.vue";
import SessionTimeline from "@/components/canvas/SessionTimeline.vue";
import CostSummaryBar from "@/components/canvas/CostSummaryBar.vue";
import RegenerateDialog from "@/components/RegenerateDialog.vue";
import type { ClipNodeData } from "@/types/clip_node";

const props = defineProps<{ storyboardId: string }>();
const router = useRouter();
const sbStore = useStoryboardStore();
const evStore = useEventsStore();
const highlightedClipIndex = ref<number | null>(null);
const regenDialogOpen = ref(false);
const selectedClip = ref<ClipNodeData | null>(null);
const jwtToken = ref(import.meta.env.VITE_DEV_JWT || "");

onMounted(async () => {
  await sbStore.load(props.storyboardId);
  await evStore.load(props.storyboardId);
});

const NODE_SPACING_X = 320;
const NODE_Y = 0;

const nodes = computed<Node[]>(() =>
  sbStore.clipNodes.map((clip, index) => ({
    id: clip.clip_id,
    type: "clipNode",
    position: { x: index * NODE_SPACING_X, y: NODE_Y },
    data: {
      clip,
      highlighted: highlightedClipIndex.value != null && clip.seq === highlightedClipIndex.value,
    },
  })),
);

const edges = computed<Edge[]>(() => {
  const clips = sbStore.clipNodes;
  const out: Edge[] = [];
  for (let index = 0; index < clips.length - 1; index += 1) {
    const source = clips[index];
    const target = clips[index + 1];
    if (!target.dependencies.chain_from_tail) continue;
    const dirty = source.review.status === "dirty" || source.review.status === "failed";
    out.push({
      id: `e_${source.clip_id}_${target.clip_id}`,
      source: source.clip_id,
      target: target.clip_id,
      type: "smoothstep",
      animated: dirty,
      style: dirty
        ? { stroke: "#dc2626", strokeWidth: 2, strokeDasharray: "6 4" }
        : { stroke: "#a8a29e", strokeWidth: 2 },
      label: dirty ? "dirty 传播" : "",
    });
  }
  return out;
});

function handleNodeSelect(clipId: string): void {
  router.push({
    name: "clip-detail",
    params: { clipId },
    query: { storyboard: props.storyboardId },
  });
}

function handleTimelineSelectClip(clipIndex: number): void {
  highlightedClipIndex.value = clipIndex;
}

function openRegenerateDialog(clip: ClipNodeData): void {
  selectedClip.value = clip;
  regenDialogOpen.value = true;
}

async function handleRegenerateCompleted(result: unknown): Promise<void> {
  const payload = result as { clip_id?: string; dirty_clip_ids?: string[] } | null;
  if (payload?.clip_id) {
    await sbStore.refreshClip(payload.clip_id);
  }
  for (const dirtyId of payload?.dirty_clip_ids ?? []) {
    sbStore.markDirty(dirtyId);
  }
}
</script>

<template>
  <div class="flex flex-col h-[calc(100vh-3.5rem)]">
    <CostSummaryBar :summary="sbStore.costSummary" :storyboard-title="sbStore.title" />

    <div class="flex items-center gap-2 px-6 py-2 bg-stone-50 border-b border-stone-200 text-sm">
      <router-link :to="{ name: 'grid', params: { storyboardId } }" class="px-3 py-1 rounded text-stone-600 hover:bg-white">
        网格视图
      </router-link>
      <span class="px-3 py-1 rounded bg-white border border-brand-300 text-brand-700 font-medium">画布视图</span>
    </div>

    <div class="flex-1 flex overflow-hidden">
      <div class="flex-1 bg-canvas-bg relative">
        <div v-if="sbStore.loading" class="absolute inset-0 flex items-center justify-center text-stone-500">加载中...</div>
        <div v-else-if="sbStore.error" class="absolute inset-0 flex items-center justify-center text-canvas-dirty">
          错误：{{ sbStore.error }}
        </div>
        <VueFlow
          v-else
          :nodes="nodes"
          :edges="edges"
          :default-viewport="{ x: 40, y: 80, zoom: 0.85 }"
          :min-zoom="0.3"
          :max-zoom="1.5"
          fit-view-on-init
          class="h-full"
          @node-click="(event) => handleNodeSelect(event.node.id)"
        >
          <template #node-clipNode="slotProps">
            <ClipFlowNode v-bind="slotProps" @select="handleNodeSelect" @regenerate="openRegenerateDialog" />
          </template>
        </VueFlow>
      </div>

      <SessionTimeline
        :events="evStore.events"
        :loading="evStore.loading"
        :highlighted-clip-index="highlightedClipIndex"
        @select-clip="handleTimelineSelectClip"
      />
    </div>

    <RegenerateDialog
      :open="regenDialogOpen"
      :clip="selectedClip"
      :token="jwtToken"
      @close="regenDialogOpen = false"
      @completed="handleRegenerateCompleted"
    />
  </div>
</template>

<style scoped>
:deep(.vue-flow__edge-text) {
  font-size: 10px;
  fill: #dc2626;
}
</style>
