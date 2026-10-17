---
title: 快速开始
description: 本地跑起 VINote 并完成第一次调用的最短路径。
---

# 快速开始

## 启动应用

后端：

```bash
pip install -r requirements.txt
python main.py
```

前端：

```bash
cd frontend
npm install
npm run web:dev
```

文档站：

```bash
cd docs
npm install
npm run docs:dev
```

默认地址：

- 应用：`http://localhost:3100`
- 后端 API：`http://127.0.0.1:8900`
- Swagger：`http://127.0.0.1:8900/docs`
- 文档站：`http://localhost:3101`

## 第一次浏览器工作流

1. 注册或登录
2. 点击 `New`
3. 选择输入方式：视频 URL、本地音频/视频文件或本地文字稿
4. 粘贴链接，或上传本地文件
5. 选择总结模式并启动生成
6. 等待任务完成
7. 在编辑器里打开生成的笔记

## 第一次 API 工作流

1. 先登录，拿到 HttpOnly 会话 Cookie
2. URL 输入调用 `POST /api/generate`
3. 本地音视频或文字稿上传调用 `POST /api/generate_from_upload`
4. 轮询 `GET /api/task/{task_id}`
5. 通过 `/api/notes` 保存或读取笔记

URL 示例：

```bash
curl -X POST http://127.0.0.1:8900/api/generate \
  -H "Content-Type: application/json" \
  -b cookie.txt -c cookie.txt \
  -d '{
    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "summary_mode": "default",
    "output_language": "zh-CN"
  }'
```

文字稿上传示例：

```bash
curl -X POST http://127.0.0.1:8900/api/generate_from_upload \
  -b cookie.txt -c cookie.txt \
  -F "file=@./meeting.srt" \
  -F "source_type=transcript" \
  -F "summary_mode=accurate" \
  -F "output_language=zh-CN"
```

字段级细节直接看 Swagger，不在这套文档里重复维护。
