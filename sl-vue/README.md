# sl-vue · 短视频生产画布

Phase F MVP（v5.1 W5.6）。Vue 3 + Vue Flow + Tailwind + Pinia 单页应用，对接 Python orchestrator 的 storyboard_api（M4 + P10 富化）。

## 启动

```bash
cd sl-vue
npm install
npm run dev
# http://localhost:5173
```

后端默认走 Vite proxy 到 `http://localhost:8000`；设置 `.env` 或 `VITE_BACKEND_BASE` 可指向其他 API。

## 路由

- `/` 入口（输入 plan_id 打开画布）
- `/canvas/:storyboardId` 画布主页（F3 实现）
- `/clip/:clipId` 单 clip 详情（F2 实现）
- `/sessions` 会话历史（F3 实现）

## Sprint 进度

- 已完成：F1 脚手架（本 commit）
- 待做：F2 ClipCard + 3 屏
- 待做：F3 CanvasView + SessionTimeline + CostSummary

## 验收

```bash
npm run type-check
npm run build
npm run dev
```
