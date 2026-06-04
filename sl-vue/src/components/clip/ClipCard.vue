<script setup lang="ts">
import { computed } from "vue";
import StatusBadge from "./StatusBadge.vue";
import MetricTile from "./MetricTile.vue";
import type { ClipNodeData } from "@/types/clip_node";

const props = defineProps<{
  clip: ClipNodeData;
  size?: "compact" | "detail";
  clickable?: boolean;
}>();

const emit = defineEmits<{
  (event: "select", clipId: string): void;
  (event: "regenerate", clip: ClipNodeData): void;
}>();

const size = computed(() => props.size ?? "compact");

const driftTone = computed<"default" | "warn" | "danger">(() => {
  const absDrift = Math.abs(props.clip.timeline.drift_sec);
  if (absDrift > 1.2) return "danger";
  if (absDrift > 0.5) return "warn";
  return "default";
});

const costTone = computed<"default" | "warn">(() => {
  return props.clip.cost.clip_cny > 2.0 ? "warn" : "default";
});

function handleClick(): void {
  if (props.clickable) emit("select", props.clip.clip_id);
}
</script>

<template>
  <div
    :class="[
      'bg-canvas-node border rounded-lg overflow-hidden transition-shadow',
      props.clip.review.status === 'dirty' ? 'border-canvas-dirty border-2' : 'border-canvas-border',
      props.clip.review.status === 'locked' ? 'border-canvas-locked' : '',
      props.clickable ? 'cursor-pointer hover:shadow-md' : '',
    ]"
    @click="handleClick"
  >
    <div class="relative bg-stone-100 aspect-[9/16]" :class="size === 'detail' ? 'max-h-96' : 'max-h-48'">
      <img
        v-if="props.clip.preview.first_frame_url"
        :src="props.clip.preview.first_frame_url"
        :alt="`clip ${props.clip.seq}`"
        class="w-full h-full object-cover"
      />
      <div v-else class="w-full h-full flex items-center justify-center text-stone-400 text-xs">无首帧</div>
      <div class="absolute top-2 left-2">
        <StatusBadge :status="props.clip.review.status" />
      </div>
      <div class="absolute top-2 right-2 text-xs bg-black/60 text-white px-1.5 py-0.5 rounded">
        seq {{ props.clip.seq }}
      </div>
      <div
        v-if="props.clip.review.dirty_reason"
        class="absolute bottom-0 left-0 right-0 bg-canvas-dirty/90 text-white text-xs px-2 py-1"
      >
        {{ props.clip.review.dirty_reason }}
      </div>
    </div>

    <div class="p-3 border-b border-stone-100">
      <div class="text-xs text-stone-500 mb-1">旁白（{{ props.clip.text.narration_segment.length }} 字）</div>
      <p :class="['text-stone-800 leading-snug', size === 'compact' ? 'text-xs line-clamp-2' : 'text-sm']">
        {{ props.clip.text.narration_segment || "（空）" }}
      </p>
    </div>

    <div class="grid grid-cols-3 gap-3 p-3 border-b border-stone-100">
      <MetricTile
        label="视频"
        :value="`${props.clip.timeline.actual_video_sec}s`"
        :hint="`目标 ${props.clip.timeline.target_video_sec}s`"
      />
      <MetricTile label="估 TTS" :value="`${props.clip.timeline.est_tts_sec}s`" />
      <MetricTile
        label="漂移"
        :value="`${props.clip.timeline.drift_sec >= 0 ? '+' : ''}${props.clip.timeline.drift_sec}s`"
        :tone="driftTone"
        :hint="driftTone === 'danger' ? '超阈值' : driftTone === 'warn' ? '可补齐' : '正常'"
      />
    </div>

    <div class="p-3 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div>
          <div class="text-xs text-stone-500">本段成本</div>
          <div :class="['text-sm font-medium', costTone === 'warn' ? 'text-amber-600' : 'text-stone-800']">
            ¥{{ props.clip.cost.clip_cny.toFixed(2) }}
          </div>
        </div>
        <div v-if="props.clip.cost.regen_count > 0">
          <div class="text-xs text-stone-500">重生</div>
          <div class="text-sm font-medium text-stone-800">{{ props.clip.cost.regen_count }} 次</div>
        </div>
      </div>
      <div v-if="props.clip.dependencies.blocking_for.length > 0" class="text-xs text-stone-400">
        阻塞 -> {{ props.clip.dependencies.blocking_for.join("/") }}
      </div>
    </div>

    <div v-if="size === 'detail'" class="p-3 border-t border-stone-100 text-xs text-stone-600 space-y-1">
      <div v-if="props.clip.text.character_id"><span class="text-stone-400">角色：</span>{{ props.clip.text.character_id }}</div>
      <div v-if="props.clip.text.environment_id"><span class="text-stone-400">场景：</span>{{ props.clip.text.environment_id }}</div>
      <div v-if="props.clip.review.last_hints.length">
        <span class="text-stone-400">上次 hints：</span>{{ props.clip.review.last_hints.join(", ") }}
      </div>
      <div v-if="props.clip.cost.risk_warning" class="text-amber-600">提示：{{ props.clip.cost.risk_warning }}</div>
    </div>

    <div class="flex justify-end border-t border-stone-100 p-3">
      <button
        type="button"
        class="rounded bg-brand-600 px-3 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:bg-stone-300"
        :disabled="props.clip.review.status === 'generating'"
        @click.stop="emit('regenerate', props.clip)"
      >
        重新生成
      </button>
    </div>
  </div>
</template>
