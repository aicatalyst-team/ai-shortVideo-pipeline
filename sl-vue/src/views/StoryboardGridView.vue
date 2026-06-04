<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";
import { useStoryboardStore } from "@/stores/storyboard";
import ClipCard from "@/components/clip/ClipCard.vue";

const props = defineProps<{ storyboardId: string }>();
const store = useStoryboardStore();
const router = useRouter();

onMounted(() => {
  store.load(props.storyboardId);
});

function openClip(clipId: string): void {
  router.push({
    name: "clip-detail",
    params: { clipId },
    query: { storyboard: props.storyboardId },
  });
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-xl font-semibold">{{ store.title || storyboardId }}</h2>
        <p class="text-sm text-stone-500 mt-1">{{ store.clipNodes.length }} 段</p>
        <div class="flex items-center gap-2 mt-3 mb-4 text-sm">
          <span class="px-3 py-1 rounded bg-white border border-brand-300 text-brand-700 font-medium">网格视图</span>
          <router-link
            :to="{ name: 'canvas', params: { storyboardId } }"
            class="px-3 py-1 rounded text-stone-600 hover:bg-stone-100 border border-transparent"
          >
            画布视图
          </router-link>
        </div>
      </div>
      <div v-if="store.costSummary" class="text-right">
        <div class="text-xs text-stone-500">累计成本</div>
        <div class="text-lg font-semibold text-stone-800">¥{{ store.costSummary.session_total_cny.toFixed(2) }}</div>
        <div class="text-xs text-stone-400">
          重生 ¥{{ store.costSummary.regen_total_cny.toFixed(2) }} · 预计继续 ¥{{
            store.costSummary.est_remaining_cny.toFixed(2)
          }}
        </div>
      </div>
    </div>

    <div v-if="store.loading" class="text-stone-500">加载中...</div>
    <div v-else-if="store.error" class="text-canvas-dirty">错误：{{ store.error }}</div>
    <div v-else-if="store.clipNodes.length" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      <ClipCard
        v-for="clip in store.clipNodes"
        :key="clip.clip_id"
        :clip="clip"
        size="compact"
        :clickable="true"
        @select="openClip"
      />
    </div>
    <div v-else class="text-stone-500">这个 storyboard 没有 clip 数据。</div>

    <div
      v-if="store.costSummary?.warnings.length"
      class="mt-6 p-3 bg-amber-50 border border-amber-300 rounded text-sm text-amber-700"
    >
      <div class="font-medium mb-1">成本警告</div>
      <ul class="list-disc list-inside">
        <li v-for="warning in store.costSummary.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </div>
  </div>
</template>
