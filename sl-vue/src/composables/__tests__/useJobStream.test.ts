import { describe, it, expect, beforeEach, vi } from "vitest";
import { useJobStream } from "../useJobStream";

class MockEventSource {
  static readonly CLOSED = 2;
  static instances: MockEventSource[] = [];

  readonly url: string;
  readyState = 1;
  listeners: Record<string, Array<(event: MessageEvent) => void>> = {};
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const fn = typeof listener === "function" ? listener : listener.handleEvent.bind(listener);
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(fn as (event: MessageEvent) => void);
  }

  emit(type: string, data: unknown): void {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    for (const listener of this.listeners[type] ?? []) {
      listener(event);
    }
  }

  close(): void {
    this.readyState = MockEventSource.CLOSED;
  }
}

describe("useJobStream", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  it("opens connection with token in query", () => {
    useJobStream("J1", "TOKEN_ABC");
    const instance = MockEventSource.instances[0];
    expect(instance.url).toContain("/api/v1/jobs/J1/stream");
    expect(instance.url).toContain("token=TOKEN_ABC");
  });

  it("updates progress on progress event", () => {
    const stream = useJobStream("J1", "T");
    const instance = MockEventSource.instances[0];

    instance.emit("progress", { progress: 30, progress_stage: "generating", status: "running" });

    expect(stream.progress.value).toBe(30);
    expect(stream.progressStage.value).toBe("generating");
    expect(stream.status.value).toBe("running");
  });

  it("sets done on completed event", () => {
    const stream = useJobStream("J1", "T");
    const instance = MockEventSource.instances[0];

    instance.emit("completed", { progress: 100, result: "{\"new_video_url\":\"x.mp4\"}" });

    expect(stream.status.value).toBe("done");
    expect(stream.progress.value).toBe(100);
    expect(stream.result.value).toEqual({ new_video_url: "x.mp4" });
  });

  it("sets failed on failed event", () => {
    const stream = useJobStream("J1", "T");
    const instance = MockEventSource.instances[0];

    instance.emit("failed", { error: "kling api 401" });

    expect(stream.status.value).toBe("failed");
    expect(stream.error.value).toBe("kling api 401");
  });

  it("close stops the stream", () => {
    const stream = useJobStream("J1", "T");
    const instance = MockEventSource.instances[0];

    stream.close();

    expect(instance.readyState).toBe(MockEventSource.CLOSED);
  });
});
