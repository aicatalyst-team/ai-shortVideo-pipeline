import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { pollJobUntilDone, type JobStatus } from "@/api/jobs";
import { getMockEvents } from "@/fixtures/events_mock";
import type { ClipReviewEvent } from "@/types/events";

const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

export const useEventsStore = defineStore("events", () => {
  const events = ref<ClipReviewEvent[]>([]);
  const loading = ref(false);
  const liveJob = ref<JobStatus | null>(null);
  const polling = ref(false);

  const recentFirst = computed(() => [...events.value].sort((a, b) => b.id - a.id));

  function setEvents(items: ClipReviewEvent[]): void {
    events.value = items;
  }

  function appendEvent(event: ClipReviewEvent): void {
    events.value.push(event);
  }

  async function load(sessionId: string): Promise<void> {
    loading.value = true;
    try {
      if (USE_MOCK) {
        events.value = getMockEvents(sessionId);
      } else {
        // TODO F4+: replace with GET /api/v1/sessions/{sessionId}/events.
        events.value = getMockEvents(sessionId);
      }
    } finally {
      loading.value = false;
    }
  }

  async function trackJob(jobId: string): Promise<JobStatus> {
    polling.value = true;
    try {
      return await pollJobUntilDone(jobId, {
        onUpdate: (job) => {
          liveJob.value = job;
        },
      });
    } finally {
      polling.value = false;
    }
  }

  return {
    events,
    loading,
    liveJob,
    polling,
    recentFirst,
    setEvents,
    appendEvent,
    load,
    trackJob,
  };
});
