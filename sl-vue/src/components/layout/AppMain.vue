<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const noPadding = computed(() => route.name === "canvas");
</script>

<template>
  <main :class="['flex-1 overflow-auto', noPadding ? '' : 'p-6']">
    <slot />
  </main>
</template>
