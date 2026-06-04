<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ status: string }>();

const styleMap: Record<string, { label: string; classes: string }> = {
  pending: { label: "待生成", classes: "bg-stone-100 text-stone-700 border-stone-300" },
  in_progress: { label: "生成中", classes: "bg-blue-50 text-blue-700 border-blue-300" },
  waiting_review: { label: "待审核", classes: "bg-amber-50 text-amber-700 border-amber-300" },
  locked: { label: "已锁定", classes: "bg-emerald-50 text-emerald-700 border-emerald-300" },
  dirty: { label: "需重生", classes: "bg-red-50 text-red-700 border-red-300" },
  cancelled: { label: "已取消", classes: "bg-stone-100 text-stone-500 border-stone-300" },
  failed: { label: "失败", classes: "bg-red-100 text-red-800 border-red-400" },
  done: { label: "完成", classes: "bg-emerald-100 text-emerald-800 border-emerald-400" },
};

const config = computed(() => styleMap[props.status] ?? styleMap.pending);
</script>

<template>
  <span :class="['inline-flex items-center px-2 py-0.5 rounded text-xs border', config.classes]">
    {{ config.label }}
  </span>
</template>
