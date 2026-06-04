<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { regenerateClip, uploadFrame, type FrameUploadResponse } from "@/api/client";
import { useJobStream } from "@/composables/useJobStream";
import type { ClipNodeData } from "@/types/clip_node";

const props = defineProps<{
  open: boolean;
  clip: ClipNodeData | null;
  token: string;
}>();

const emit = defineEmits<{
  (event: "close"): void;
  (event: "completed", result: unknown): void;
}>();

const phase = ref<"form" | "running" | "done" | "failed">("form");
const newPrompt = ref("");
const uploadedFrame = ref<FrameUploadResponse | null>(null);
const uploadError = ref("");
const jobId = ref("");
const progress = ref(0);
const progressStage = ref("");
const result = ref<unknown>(null);
const errorMsg = ref("");
const connectionState = ref<"idle" | "connected" | "reconnecting">("idle");
const startedAtMs = ref(0);

let streamCleanup: (() => void) | null = null;

const canSubmit = computed(() => Boolean(props.clip) && (!!newPrompt.value.trim() || !!uploadedFrame.value));

const stageLabel = computed(() => {
  const labels: Record<string, string> = {
    starting: "启动任务",
    generating_video: "生成视频",
    extracting_tail_frame: "抽取尾帧",
    updating_db: "保存结果",
    done: "完成",
    failed: "失败",
  };
  return labels[progressStage.value] || progressStage.value || "准备中";
});

const eta = computed(() => {
  if (progress.value <= 0 || progress.value >= 100 || startedAtMs.value <= 0) return null;
  const elapsed = (Date.now() - startedAtMs.value) / 1000;
  const total = (elapsed * 100) / progress.value;
  return Math.max(0, Math.round(total - elapsed));
});

watch(
  () => props.open,
  (open) => {
    if (open) resetForm();
  },
);

async function onFileSelect(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;

  uploadError.value = "";
  try {
    uploadedFrame.value = await uploadFrame(file, "upload", props.token);
  } catch (err) {
    uploadError.value = extractError(err, "上传失败");
  }
}

async function submit(): Promise<void> {
  if (!props.clip || !canSubmit.value) return;

  try {
    const payload: { new_prompt?: string; new_first_frame_url?: string } = {};
    if (newPrompt.value.trim()) payload.new_prompt = newPrompt.value.trim();
    if (uploadedFrame.value) payload.new_first_frame_url = uploadedFrame.value.url;

    const accepted = await regenerateClip(props.clip.clip_id, payload);
    jobId.value = accepted.job_id;
    phase.value = "running";
    startedAtMs.value = Date.now();
    subscribeToJobStream();
  } catch (err) {
    errorMsg.value = extractError(err, "提交失败");
    phase.value = "failed";
  }
}

function subscribeToJobStream(): void {
  if (!jobId.value) return;

  cleanup();
  const stream = useJobStream(jobId.value, props.token);
  const unwatch = watch(
    [stream.progress, stream.progressStage, stream.status, stream.error, stream.result],
    ([nextProgress, nextStage, nextStatus, nextError, nextResult]) => {
      progress.value = nextProgress;
      progressStage.value = nextStage;

      if (nextStatus === "done") {
        result.value = nextResult;
        phase.value = "done";
        emit("completed", nextResult);
        cleanup();
      } else if (nextStatus === "failed") {
        errorMsg.value = nextError;
        phase.value = "failed";
        cleanup();
      } else if (nextStatus === "disconnected") {
        connectionState.value = "reconnecting";
      } else {
        connectionState.value = "connected";
      }
    },
  );

  streamCleanup = () => {
    unwatch();
    stream.close();
  };
}

function cleanup(): void {
  if (streamCleanup) {
    streamCleanup();
    streamCleanup = null;
  }
}

function resetForm(): void {
  cleanup();
  phase.value = "form";
  newPrompt.value = "";
  uploadedFrame.value = null;
  uploadError.value = "";
  jobId.value = "";
  progress.value = 0;
  progressStage.value = "";
  result.value = null;
  errorMsg.value = "";
  connectionState.value = "idle";
  startedAtMs.value = 0;
}

function cancel(): void {
  resetForm();
  emit("close");
}

function close(): void {
  resetForm();
  emit("close");
}

function retry(): void {
  cleanup();
  phase.value = "form";
  errorMsg.value = "";
}

function extractError(err: unknown, fallback: string): string {
  if (typeof err === "object" && err && "response" in err) {
    const response = (err as { response?: { data?: { message?: string; detail?: string } } }).response;
    return response?.data?.message || response?.data?.detail || fallback;
  }
  return err instanceof Error ? err.message : fallback;
}
</script>

<template>
  <div v-if="props.open && props.clip" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
    <div class="w-full max-w-xl rounded-lg bg-white shadow-2xl">
      <div class="flex items-center justify-between border-b border-stone-200 px-5 py-4">
        <h2 class="text-base font-semibold text-stone-900">重新生成 Clip #{{ props.clip.seq }}</h2>
        <button class="text-2xl leading-none text-stone-400 hover:text-stone-700" type="button" @click="cancel">
          x
        </button>
      </div>

      <div v-if="phase === 'form'" class="space-y-4 p-5">
        <div>
          <label class="mb-1 block text-sm font-medium text-stone-700">当前 prompt</label>
          <div class="max-h-24 overflow-y-auto rounded border border-stone-200 bg-stone-50 p-2 text-xs text-stone-600">
            {{ props.clip.text.visual_prompt || props.clip.text.narration_segment || "(empty)" }}
          </div>
        </div>

        <div>
          <label class="mb-1 block text-sm font-medium text-stone-700">新 prompt</label>
          <textarea
            v-model="newPrompt"
            class="min-h-24 w-full resize-y rounded border border-stone-300 p-2 text-sm outline-none focus:border-brand-500"
            placeholder="输入新的画面提示词"
          />
        </div>

        <div>
          <label class="mb-1 block text-sm font-medium text-stone-700">新首帧</label>
          <input
            class="block w-full text-sm text-stone-600"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            @change="onFileSelect"
          />
          <div v-if="uploadedFrame" class="mt-2 text-xs text-emerald-700">
            已上传 {{ uploadedFrame.width }}x{{ uploadedFrame.height }}
            <span v-if="uploadedFrame.dedup">，去重命中</span>
          </div>
          <div v-if="uploadError" class="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">{{ uploadError }}</div>
        </div>

        <div class="flex justify-end gap-2 pt-2">
          <button class="rounded border border-stone-300 px-4 py-2 text-sm text-stone-700 hover:bg-stone-50" type="button" @click="cancel">
            取消
          </button>
          <button
            class="rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:bg-stone-300"
            type="button"
            :disabled="!canSubmit"
            @click="submit"
          >
            提交重生成
          </button>
        </div>
      </div>

      <div v-else-if="phase === 'running'" class="space-y-4 p-5">
        <div class="flex items-baseline justify-between">
          <div class="text-sm font-medium text-stone-800">{{ stageLabel }}</div>
          <div class="text-sm text-stone-500">{{ progress }}%</div>
        </div>
        <div class="h-2 overflow-hidden rounded bg-stone-200">
          <div class="h-full rounded bg-brand-600 transition-all duration-300" :style="{ width: `${progress}%` }" />
        </div>
        <div class="flex justify-between text-xs text-stone-500">
          <span>job_id: {{ jobId }}</span>
          <span v-if="eta !== null">预计剩余 {{ eta }}s</span>
          <span v-if="connectionState === 'reconnecting'" class="text-amber-600">重连中</span>
        </div>
      </div>

      <div v-else-if="phase === 'done'" class="space-y-4 p-6 text-center">
        <div class="text-xl font-semibold text-emerald-700">重生成完成</div>
        <div
          v-if="(result as any)?.dirty_clip_ids?.length"
          class="rounded bg-amber-50 p-3 text-left text-sm text-amber-800"
        >
          后续 {{ (result as any).dirty_clip_ids.length }} 段已标记 dirty：
          <code class="text-xs">{{ (result as any).dirty_clip_ids.join(", ") }}</code>
        </div>
        <button class="rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white" type="button" @click="close">
          关闭
        </button>
      </div>

      <div v-else class="space-y-4 p-6 text-center">
        <div class="text-xl font-semibold text-red-700">重生成失败</div>
        <div class="max-h-40 overflow-y-auto rounded bg-red-50 p-3 text-sm text-red-700">
          {{ errorMsg || "未知错误" }}
        </div>
        <div class="flex justify-center gap-2">
          <button class="rounded border border-stone-300 px-4 py-2 text-sm" type="button" @click="retry">重试</button>
          <button class="rounded bg-stone-600 px-4 py-2 text-sm font-medium text-white" type="button" @click="close">
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
