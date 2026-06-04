import client from "./client";

export interface JobStatus {
  id: string;
  status: string;
  progress: number;
  progress_stage: string;
  target_id?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  updated_at?: string;
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const resp = await client.get<JobStatus>(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
  return resp.data;
}

export async function pollJobUntilDone(
  jobId: string,
  options: { intervalMs?: number; timeoutMs?: number; onUpdate?: (job: JobStatus) => void } = {},
): Promise<JobStatus> {
  const interval = options.intervalMs ?? 500;
  const timeout = options.timeoutMs ?? 10 * 60 * 1000;
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const job = await fetchJob(jobId);
    options.onUpdate?.(job);
    if (job.status === "done" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }
  throw new Error(`job ${jobId} 轮询超时 (${timeout}ms)`);
}
