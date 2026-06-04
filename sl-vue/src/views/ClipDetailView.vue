<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useStoryboardStore } from "@/stores/storyboard";
import ClipCard from "@/components/clip/ClipCard.vue";
import ReviewOpsPanel from "@/components/clip/ReviewOpsPanel.vue";

const props = defineProps<{ clipId: string }>();
const store = useStoryboardStore();
const router = useRouter();
const route = useRoute();

const storyboardId = computed(() => {
  const value = route.query.storyboard;
  return typeof value === "string" ? value : undefined;
});

onMounted(() => {
  if (storyboardId.value && !store.current) {
    store.load(storyboardId.value);
  }
});

const clip = computed(() => store.clipNodes.find((item) => item.clip_id === props.clipId) ?? null);

function handleContinue(): void {
  console.log("[clip-detail] continue", props.clipId);
  alert(`继续 clip ${props.clipId}（真调用留 F3 后续）`);
}

function handleRegen(payload: { hints: string[]; customNote: string }): void {
  console.log("[clip-detail] regenerate", props.clipId, payload);
  alert(
    `重生成 clip ${props.clipId}\n` +
      `hints: ${payload.hints.join(", ") || "（无）"}\n` +
      `备注：${payload.customNote || "（无）"}\n` +
      "（真调用留 F3 后续）",
  );
}

function handleCancel(): void {
  console.log("[clip-detail] cancel", props.clipId);
  alert(`取消 clip ${props.clipId}（真调用留 F3 后续）`);
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <button class="text-sm text-stone-600 hover:text-brand-600" @click="router.back()">← 返回</button>
      <span class="text-sm text-stone-500">clip {{ clipId }}</span>
    </div>

    <div v-if="!clip" class="text-stone-500">
      clip 未加载。请从网格点击进入（直接打开链接需带 ?storyboard=plan_id）。
    </div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <ClipCard :clip="clip" size="detail" />
      <div class="space-y-4">
        <ReviewOpsPanel :clip="clip" @continue="handleContinue" @regenerate="handleRegen" @cancel="handleCancel" />

        <div class="border border-stone-200 rounded-lg p-4 bg-white">
          <h3 class="text-sm font-semibold text-stone-800 mb-2">依赖关系</h3>
          <div class="text-xs text-stone-600 space-y-1">
            <div>
              <span class="text-stone-400">上游（首帧来自）：</span>
              <span v-if="clip.dependencies.depends_on.length">clip {{ clip.dependencies.depends_on.join("/") }}</span>
              <span v-else>无（首段或链式断裂）</span>
            </div>
            <div>
              <span class="text-stone-400">下游（重生影响）：</span>
              <span v-if="clip.dependencies.blocking_for.length">clip {{ clip.dependencies.blocking_for.join("/") }}</span>
              <span v-else>无（末段）</span>
            </div>
          </div>
          <div
            v-if="clip.dependencies.blocking_for.length"
            class="mt-3 text-xs bg-amber-50 border border-amber-300 rounded p-2 text-amber-700"
          >
            重生成本段会让 clip {{ clip.dependencies.blocking_for.join("/") }} 标 dirty。
          </div>
        </div>

        <div class="border border-stone-200 rounded-lg p-4 bg-white">
          <h3 class="text-sm font-semibold text-stone-800 mb-2">完整 Prompt</h3>
          <div class="text-xs space-y-2">
            <div>
              <div class="text-stone-400">visual_prompt</div>
              <div class="text-stone-700 font-mono break-all">{{ clip.text.visual_prompt }}</div>
            </div>
            <div>
              <div class="text-stone-400">kling_prompt</div>
              <div class="text-stone-700 font-mono break-all">{{ clip.text.kling_prompt }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
