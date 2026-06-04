<script setup lang="ts">
import { computed } from "vue";
import type { ClipReviewEvent } from "@/types/events";

const props = defineProps<{
  events: ClipReviewEvent[];
  loading?: boolean;
  highlightedClipIndex?: number | null;
}>();

const emit = defineEmits<{ (event: "select-clip", clipIndex: number): void }>();

const STAGE_ICONS: Record<string, string> = {
  session: "📦",
  character: "👤",
  scene: "🏞️",
  refimg: "🖼️",
  storyboard: "📋",
  clip: "🎬",
  final: "🎞️",
};

const DECISION_TONE: Record<string, string> = {
  created: "text-stone-600",
  continue: "text-emerald-600",
  approved: "text-emerald-600",
  locked: "text-emerald-700",
  completed: "text-emerald-700",
  regen: "text-amber-600",
  cancel: "text-stone-500",
  rejected: "text-canvas-dirty",
  failed: "text-canvas-dirty",
};

const sorted = computed(() => [...props.events].sort((a, b) => a.id - b.id));

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function isHighlighted(event: ClipReviewEvent): boolean {
  return props.highlightedClipIndex != null && event.clip_index === props.highlightedClipIndex;
}

function clickEvent(event: ClipReviewEvent): void {
  if (event.clip_index != null) emit("select-clip", event.clip_index);
}
</script>

<template>
  <aside class="w-72 bg-white border-l border-stone-200 flex flex-col h-full">
    <div class="px-4 py-3 border-b border-stone-200">
      <h3 class="text-sm font-semibold text-stone-800">审核轨迹</h3>
      <p class="text-xs text-stone-400 mt-0.5">{{ sorted.length }} 条事件</p>
    </div>

    <div class="flex-1 overflow-y-auto px-2 py-2 space-y-1">
      <div v-if="loading" class="text-xs text-stone-500 px-2 py-4">加载中...</div>
      <div v-else-if="sorted.length === 0" class="text-xs text-stone-400 px-2 py-4">无事件</div>
      <div
        v-for="event in sorted"
        :key="event.id"
        :data-testid="event.clip_index != null ? `timeline-clip-${event.clip_index}` : `timeline-event-${event.id}`"
        :class="[
          'px-2 py-2 rounded text-xs cursor-pointer transition-colors',
          isHighlighted(event) ? 'bg-brand-50 border border-brand-300' : 'hover:bg-stone-50',
        ]"
        @click="clickEvent(event)"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-1.5">
            <span class="text-base">{{ STAGE_ICONS[event.stage] ?? '•' }}</span>
            <span class="text-stone-500">{{ event.stage }}</span>
            <span :class="['font-medium', DECISION_TONE[event.decision] ?? 'text-stone-700']">
              {{ event.decision }}
            </span>
          </div>
          <span class="text-stone-400 text-[10px]">{{ fmtTime(event.created_at) }}</span>
        </div>
        <div v-if="event.clip_index != null" class="text-stone-500 mt-0.5">clip {{ event.clip_index }}</div>
        <div v-if="event.comment" class="text-stone-700 mt-0.5 line-clamp-2">{{ event.comment }}</div>
        <div v-if="event.hints && event.hints.length" class="flex flex-wrap gap-1 mt-1">
          <span v-for="hint in event.hints" :key="hint" class="px-1.5 py-0.5 bg-brand-50 text-brand-700 rounded text-[10px]">
            {{ hint }}
          </span>
        </div>
      </div>
    </div>
  </aside>
</template>
