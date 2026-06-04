<script setup lang="ts">
import { Handle, Position } from "@vue-flow/core";
import ClipCard from "@/components/clip/ClipCard.vue";
import type { ClipNodeData } from "@/types/clip_node";

defineProps<{
  data: { clip: ClipNodeData; highlighted?: boolean };
}>();

const emit = defineEmits<{
  (event: "select", clipId: string): void;
  (event: "regenerate", clip: ClipNodeData): void;
}>();
</script>

<template>
  <div :class="['transition-all', data.highlighted ? 'ring-4 ring-brand-500 ring-offset-2 rounded-lg' : '']" style="width: 280px">
    <Handle type="target" :position="Position.Left" class="!bg-stone-400" />
    <ClipCard
      :clip="data.clip"
      size="compact"
      :clickable="true"
      @select="(id) => emit('select', id)"
      @regenerate="(clip) => emit('regenerate', clip)"
    />
    <Handle type="source" :position="Position.Right" class="!bg-stone-400" />
  </div>
</template>
