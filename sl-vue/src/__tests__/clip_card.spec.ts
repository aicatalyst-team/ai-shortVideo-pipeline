import { beforeEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import ClipCard from "@/components/clip/ClipCard.vue";
import { MOCK_STORYBOARD } from "@/fixtures/storyboard_mock";

describe("ClipCard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders status badge for pending clip", () => {
    const clip = MOCK_STORYBOARD.clip_nodes[0];
    const wrapper = mount(ClipCard, { props: { clip } });
    expect(wrapper.text()).toContain("待生成");
  });

  it("shows dirty reason banner when status=dirty", () => {
    const clip = MOCK_STORYBOARD.clip_nodes[2];
    const wrapper = mount(ClipCard, { props: { clip } });
    expect(wrapper.text()).toContain("人物近 + 不要文字");
  });

  it("emits select event when clickable and clicked", async () => {
    const clip = MOCK_STORYBOARD.clip_nodes[0];
    const wrapper = mount(ClipCard, { props: { clip, clickable: true } });
    await wrapper.trigger("click");
    expect(wrapper.emitted("select")).toBeTruthy();
    expect(wrapper.emitted("select")![0]).toEqual([clip.clip_id]);
  });

  it("renders cost with warn tone for high cost", () => {
    const clip = {
      ...MOCK_STORYBOARD.clip_nodes[0],
      cost: { ...MOCK_STORYBOARD.clip_nodes[0].cost, clip_cny: 2.5 },
    };
    const wrapper = mount(ClipCard, { props: { clip } });
    expect(wrapper.html()).toContain("text-amber-600");
  });
});
