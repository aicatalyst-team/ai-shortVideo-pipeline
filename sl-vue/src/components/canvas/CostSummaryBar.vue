<script setup lang="ts">
import type { CostSummary } from "@/types/clip_node";

defineProps<{ summary: CostSummary | null; storyboardTitle?: string }>();
</script>

<template>
  <div class="bg-white border-b border-stone-200 px-6 py-3 flex items-center justify-between">
    <div>
      <h2 class="text-base font-semibold text-stone-800">{{ storyboardTitle || "（无标题）" }}</h2>
      <p v-if="summary" class="text-xs text-stone-500 mt-0.5">
        {{ summary.clip_count }} 段 · 平均 ¥{{ summary.cost_per_clip_avg.toFixed(2) }}/段
      </p>
    </div>
    <div v-if="summary" class="flex items-center gap-6 text-right">
      <div>
        <div class="text-xs text-stone-500">累计成本</div>
        <div class="text-lg font-semibold text-stone-800">¥{{ summary.session_total_cny.toFixed(2) }}</div>
      </div>
      <div>
        <div class="text-xs text-stone-500">重生成</div>
        <div class="text-base font-medium text-amber-600">¥{{ summary.regen_total_cny.toFixed(2) }}</div>
      </div>
      <div>
        <div class="text-xs text-stone-500">预计继续</div>
        <div class="text-base font-medium text-stone-700">¥{{ summary.est_remaining_cny.toFixed(2) }}</div>
      </div>
    </div>
    <div v-else class="text-xs text-stone-400">无成本数据</div>
  </div>
</template>
