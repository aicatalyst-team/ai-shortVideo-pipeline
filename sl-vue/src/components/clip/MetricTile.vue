<script setup lang="ts">
defineProps<{ label: string; value: string; hint?: string; tone?: "default" | "warn" | "danger" }>();
</script>

<template>
  <div class="flex flex-col gap-0.5">
    <div class="text-xs text-stone-500">{{ label }}</div>
    <div
      :class="[
        'text-sm font-medium',
        tone === 'warn' ? 'text-amber-600' : tone === 'danger' ? 'text-canvas-dirty' : 'text-stone-800',
      ]"
    >
      {{ value }}
    </div>
    <div v-if="hint" class="text-[10px] text-stone-400">{{ hint }}</div>
  </div>
</template>
