<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <header class="bg-white border-b border-stone-200 px-6 py-3 flex items-center justify-between">
    <div class="flex items-center gap-4">
      <RouterLink to="/" class="text-xl font-semibold text-brand-700">sl-vue</RouterLink>
      <span class="text-sm text-stone-500">短视频生产画布</span>
    </div>
    <nav class="flex items-center gap-4 text-sm">
      <RouterLink to="/" class="text-stone-700 hover:text-brand-600">首页</RouterLink>
      <RouterLink to="/sessions" class="text-stone-700 hover:text-brand-600">会话历史</RouterLink>
    </nav>
  </header>
</template>
