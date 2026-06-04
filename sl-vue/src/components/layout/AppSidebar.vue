<template>
  <aside class="w-56 bg-white border-r border-stone-200 p-4">
    <div class="text-xs uppercase tracking-wider text-stone-400 mb-2">演示</div>
    <ul class="space-y-1 text-sm">
      <li>
        <router-link
          :to="{ name: 'grid', params: { storyboardId: 'MOCK001' } }"
          class="block px-2 py-1 rounded text-stone-700 hover:bg-stone-100"
        >
          网格视图
        </router-link>
      </li>
      <li>
        <router-link
          :to="{ name: 'canvas', params: { storyboardId: 'MOCK001' } }"
          class="block px-2 py-1 rounded text-stone-700 hover:bg-stone-100"
        >
          画布视图
        </router-link>
      </li>
    </ul>
    <div class="text-xs uppercase tracking-wider text-stone-400 mt-6 mb-2">F4 待加</div>
    <ul class="space-y-1 text-sm">
      <li class="text-stone-400">SSE 实时进度</li>
      <li class="text-stone-400">真实 events API</li>
    </ul>
  </aside>
</template>
