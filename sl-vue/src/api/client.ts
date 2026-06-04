import axios, { type AxiosError, type AxiosInstance } from "axios";

const GATEWAY_BASE = import.meta.env.VITE_GATEWAY_BASE || "http://localhost:8080";
const PYTHON_BASE = import.meta.env.VITE_PYTHON_BASE || "http://localhost:8000";

const client: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_BACKEND_BASE || "",
  timeout: 15_000,
});

client.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response) {
      console.error(
        `[api] ${err.config?.method?.toUpperCase()} ${err.config?.url} -> ${err.response.status}`,
        err.response.data,
      );
    } else {
      console.error("[api] network error:", err.message);
    }
    return Promise.reject(err);
  },
);

export interface FrameUploadResponse {
  asset_id: string;
  url: string;
  thumb_url: string;
  sha256: string;
  width: number;
  height: number;
  size_bytes: number;
  dedup: boolean;
}

export interface RegeneratePayload {
  new_prompt?: string;
  new_kling_prompt?: string;
  new_first_frame_url?: string;
}

export interface RegenerateAcceptedResponse {
  job_id: string;
  clip_id: string;
  status: string;
  poll_url: string;
}

export async function uploadFrame(file: File, kind = "upload", token: string): Promise<FrameUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);

  const resp = await axios.post<FrameUploadResponse>(`${GATEWAY_BASE}/api/v1/frames/upload`, form, {
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "multipart/form-data",
    },
    timeout: 30_000,
  });
  return resp.data;
}

export async function regenerateClip(
  clipId: string,
  payload: RegeneratePayload,
): Promise<RegenerateAcceptedResponse> {
  const resp = await axios.post<RegenerateAcceptedResponse>(
    `${PYTHON_BASE}/api/v1/clips/${encodeURIComponent(clipId)}/regenerate`,
    payload,
    { timeout: 10_000 },
  );
  return resp.data;
}

export async function pollJob(jobId: string): Promise<unknown> {
  const resp = await axios.get(`${PYTHON_BASE}/api/v1/jobs/${encodeURIComponent(jobId)}`, { timeout: 5_000 });
  return resp.data;
}

export default client;
