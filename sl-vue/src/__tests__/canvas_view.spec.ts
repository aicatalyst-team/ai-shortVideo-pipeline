import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import SessionTimeline from "@/components/canvas/SessionTimeline.vue";
import CostSummaryBar from "@/components/canvas/CostSummaryBar.vue";
import { MOCK_EVENTS } from "@/fixtures/events_mock";
import { MOCK_STORYBOARD } from "@/fixtures/storyboard_mock";

describe("SessionTimeline", () => {
  it("renders all events with stage icons", () => {
    const wrapper = mount(SessionTimeline, { props: { events: MOCK_EVENTS } });
    const html = wrapper.html();
    expect(html).toContain("📦");
    expect(html).toContain("🎬");
    expect(html).toContain("🎞️");
  });

  it("shows hints chips for regen events", () => {
    const wrapper = mount(SessionTimeline, { props: { events: MOCK_EVENTS } });
    expect(wrapper.text()).toContain("closer_shot");
    expect(wrapper.text()).toContain("no_text");
  });

  it("highlights matching clip when prop set", () => {
    const wrapper = mount(SessionTimeline, {
      props: { events: MOCK_EVENTS, highlightedClipIndex: 3 },
    });
    expect(wrapper.html()).toContain("bg-brand-50");
  });

  it("emits select-clip on clip event click", async () => {
    const wrapper = mount(SessionTimeline, { props: { events: MOCK_EVENTS } });
    await wrapper.get("[data-testid='timeline-clip-1']").trigger("click");
    expect(wrapper.emitted("select-clip")).toBeTruthy();
    expect(wrapper.emitted("select-clip")![0]).toEqual([1]);
  });
});

describe("CostSummaryBar", () => {
  it("renders zero state when summary is null", () => {
    const wrapper = mount(CostSummaryBar, { props: { summary: null } });
    expect(wrapper.text()).toContain("无成本数据");
  });

  it("formats currency to 2 decimals", () => {
    const wrapper = mount(CostSummaryBar, {
      props: { summary: MOCK_STORYBOARD.cost_summary!, storyboardTitle: "测试" },
    });
    expect(wrapper.text()).toContain("¥3.55");
    expect(wrapper.text()).toContain("¥1.22");
    expect(wrapper.text()).toContain("¥0.60");
  });

  it("shows storyboard title", () => {
    const wrapper = mount(CostSummaryBar, {
      props: { summary: MOCK_STORYBOARD.cost_summary!, storyboardTitle: "AI 短视频" },
    });
    expect(wrapper.text()).toContain("AI 短视频");
  });
});
