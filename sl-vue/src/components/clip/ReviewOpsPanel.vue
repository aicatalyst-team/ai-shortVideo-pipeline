<script setup lang="ts">
import { computed, ref } from "vue";
import type { ClipNodeData } from "@/types/clip_node";

const HINT_LABELS: Array<{ key: string; label: string; group: string }> = [
  { key: "closer_shot", label: "人物近", group: "镜头" },
  { key: "wider_shot", label: "镜头远", group: "镜头" },
  { key: "more_realistic", label: "更真实", group: "风格" },
  { key: "more_dramatic", label: "更戏剧", group: "风格" },
  { key: "no_text", label: "不要文字", group: "约束" },
  { key: "brighter", label: "亮一点", group: "光线" },
  { key: "darker", label: "暗一点", group: "光线" },
  { key: "warmer_tone", label: "暖色调", group: "光线" },
  { key: "cooler_tone", label: "冷色调", group: "光线" },
  { key: "more_motion", label: "更动态", group: "运动" },
  { key: "static_shot", label: "固定镜头", group: "运动" },
  { key: "different_character", label: "换主角", group: "高级" },
  { key: "different_scene", label: "换场景", group: "高级" },
];

const props = defineProps<{ clip: ClipNodeData }>();
const emit = defineEmits<{
  (event: "continue"): void;
  (event: "regenerate", payload: { hints: string[]; customNote: string }): void;
  (event: "cancel"): void;
}>();

const selectedHints = ref<Set<string>>(new Set());
const customNote = ref("");
const mode = ref<"idle" | "regen">("idle");

const groups = computed(() => {
  const grouped = new Map<string, typeof HINT_LABELS>();
  for (const hint of HINT_LABELS) {
    if (!grouped.has(hint.group)) grouped.set(hint.group, []);
    grouped.get(hint.group)!.push(hint);
  }
  return Array.from(grouped.entries());
});

function toggleHint(key: string): void {
  const next = new Set(selectedHints.value);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  selectedHints.value = next;
}

function submitRegen(): void {
  emit("regenerate", {
    hints: Array.from(selectedHints.value),
    customNote: customNote.value.trim(),
  });
  selectedHints.value = new Set();
  customNote.value = "";
  mode.value = "idle";
}
</script>

<template>
  <div class="border border-stone-200 rounded-lg p-4 bg-white">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-stone-800">审核操作</h3>
      <span class="text-xs text-stone-400">clip {{ props.clip.seq }} · {{ props.clip.review.status }}</span>
    </div>

    <div v-if="mode === 'idle'" class="flex gap-2">
      <button
        :disabled="!props.clip.ops.can_continue"
        class="flex-1 px-3 py-2 bg-emerald-600 text-white text-sm rounded hover:bg-emerald-700 disabled:bg-stone-300 disabled:cursor-not-allowed"
        @click="emit('continue')"
      >
        1.继续
      </button>
      <button
        :disabled="!props.clip.ops.can_regenerate"
        class="flex-1 px-3 py-2 bg-amber-600 text-white text-sm rounded hover:bg-amber-700 disabled:bg-stone-300 disabled:cursor-not-allowed"
        @click="mode = 'regen'"
      >
        2.重新生成
      </button>
      <button
        :disabled="!props.clip.ops.can_cancel"
        class="flex-1 px-3 py-2 bg-stone-600 text-white text-sm rounded hover:bg-stone-700 disabled:bg-stone-300 disabled:cursor-not-allowed"
        @click="emit('cancel')"
      >
        3.取消
      </button>
    </div>

    <div v-else class="space-y-3">
      <div v-for="[group, items] in groups" :key="group">
        <div class="text-xs text-stone-500 mb-1">{{ group }}</div>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="hint in items"
            :key="hint.key"
            :class="[
              'px-2 py-1 text-xs border rounded transition-colors',
              selectedHints.has(hint.key)
                ? 'bg-brand-500 text-white border-brand-500'
                : 'bg-white text-stone-700 border-stone-300 hover:border-brand-400',
            ]"
            @click="toggleHint(hint.key)"
          >
            {{ hint.label }}
          </button>
        </div>
      </div>

      <div>
        <div class="text-xs text-stone-500 mb-1">自由备注（可选）</div>
        <input
          v-model="customNote"
          type="text"
          placeholder="例：换成办公室场景"
          class="w-full border border-stone-300 rounded px-2 py-1 text-sm focus:outline-none focus:border-brand-500"
        />
      </div>

      <div class="flex gap-2">
        <button class="flex-1 px-3 py-2 bg-brand-600 text-white text-sm rounded hover:bg-brand-700" @click="submitRegen">
          提交重生（{{ selectedHints.size }} hints{{ customNote ? " + 备注" : "" }}）
        </button>
        <button class="px-3 py-2 bg-stone-200 text-stone-700 text-sm rounded hover:bg-stone-300" @click="mode = 'idle'">
          返回
        </button>
      </div>
    </div>
  </div>
</template>
