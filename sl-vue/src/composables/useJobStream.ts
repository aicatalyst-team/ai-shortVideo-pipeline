import { getCurrentScope, onScopeDispose, ref, type Ref } from "vue";

export interface JobStreamState {
  status: Ref<string>;
  progress: Ref<number>;
  progressStage: Ref<string>;
  result: Ref<unknown>;
  error: Ref<string>;
  lastUpdateMs: Ref<number>;
  activeConnections: Ref<number>;
  close: () => void;
}

const GATEWAY_BASE = import.meta.env.VITE_GATEWAY_BASE || "http://localhost:8080";

function parseJson(data: string): Record<string, unknown> {
  try {
    return JSON.parse(data) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

export function useJobStream(jobId: string, token: string): JobStreamState {
  const status = ref("queued");
  const progress = ref(0);
  const progressStage = ref("");
  const result = ref<unknown>(null);
  const error = ref("");
  const lastUpdateMs = ref(Date.now());
  const activeConnections = ref(0);

  const url = `${GATEWAY_BASE}/api/v1/jobs/${encodeURIComponent(jobId)}/stream?token=${encodeURIComponent(token)}`;
  let es: EventSource | null = null;

  function markUpdated(): void {
    lastUpdateMs.value = Date.now();
  }

  function close(): void {
    if (es) {
      es.close();
      es = null;
    }
  }

  function open(): void {
    es = new EventSource(url);
    activeConnections.value += 1;

    es.onmessage = () => {
      markUpdated();
    };

    es.addEventListener("stream_opened", (ev) => {
      markUpdated();
      const data = parseJson((ev as MessageEvent).data);
      const resumeFrom = Number(data.resume_from ?? 0);
      if (!Number.isNaN(resumeFrom)) {
        progress.value = Math.max(progress.value, resumeFrom);
      }
      status.value = "connected";
    });

    es.addEventListener("progress", (ev) => {
      markUpdated();
      const data = parseJson((ev as MessageEvent).data);
      const nextProgress = Number(data.progress ?? progress.value);
      if (!Number.isNaN(nextProgress)) progress.value = nextProgress;
      progressStage.value = String(data.progress_stage ?? "");
      status.value = String(data.status ?? "running");
    });

    es.addEventListener("completed", (ev) => {
      markUpdated();
      const data = parseJson((ev as MessageEvent).data);
      progress.value = 100;
      progressStage.value = "done";
      status.value = "done";
      result.value = parseMaybeJson(data.result);
      close();
    });

    es.addEventListener("failed", (ev) => {
      markUpdated();
      const data = parseJson((ev as MessageEvent).data);
      status.value = "failed";
      progressStage.value = "failed";
      error.value = String(data.error ?? "unknown error");
      close();
    });

    es.addEventListener("cancelled", () => {
      markUpdated();
      status.value = "cancelled";
      close();
    });

    es.onerror = () => {
      if (es && es.readyState === EventSource.CLOSED) {
        status.value = "disconnected";
      }
    };
  }

  open();

  if (getCurrentScope()) {
    onScopeDispose(close);
  }

  return {
    status,
    progress,
    progressStage,
    result,
    error,
    lastUpdateMs,
    activeConnections,
    close,
  };
}
