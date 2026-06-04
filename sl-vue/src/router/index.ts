import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    component: () => import("@/views/HomeView.vue"),
  },
  {
    path: "/sessions",
    name: "sessions",
    component: () => import("@/views/SessionsView.vue"),
  },
  {
    path: "/canvas/:storyboardId",
    name: "canvas",
    component: () => import("@/views/CanvasView.vue"),
    props: true,
  },
  {
    path: "/clip/:clipId",
    name: "clip-detail",
    component: () => import("@/views/ClipDetailView.vue"),
    props: true,
  },
  {
    path: "/grid/:storyboardId",
    name: "grid",
    component: () => import("@/views/StoryboardGridView.vue"),
    props: true,
  },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
