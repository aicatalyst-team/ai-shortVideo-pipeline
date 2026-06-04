<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();
const planId = ref("");

function open(): void {
  const value = planId.value.trim();
  if (value) {
    router.push({ name: "grid", params: { storyboardId: value } });
  }
}

function openMock(): void {
  router.push({ name: "grid", params: { storyboardId: "MOCK001" } });
}
</script>

<template>
  <div class="max-w-xl">
    <h1 class="text-2xl font-semibold mb-4">短视频生产画布</h1>
    <p class="text-stone-600 mb-6">输入 plan_id 打开对应 storyboard 的网格视图。</p>
    <div class="flex gap-2 mb-3">
      <input
        v-model="planId"
        type="text"
        placeholder="plan_id（如 P001）"
        class="flex-1 border border-stone-300 rounded px-3 py-2 text-sm focus:outline-none focus:border-brand-500"
        @keyup.enter="open"
      />
      <button class="px-4 py-2 bg-brand-600 text-white rounded text-sm hover:bg-brand-700" @click="open">
        打开网格
      </button>
    </div>
    <button class="text-sm text-brand-600 hover:underline" @click="openMock">
      用 mock 数据演示（5 段，覆盖 5 状态）
    </button>
  </div>
</template>
