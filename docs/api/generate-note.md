---
title: 生成笔记
description: 如何创建 URL 或上传驱动的笔记生成任务，以及后续应如何处理。
---

# 生成笔记

## 常用异步接口

- `POST /api/generate`
- `POST /api/generate_from_upload`

## 常用同步接口

- `POST /api/generate_sync`
- `POST /api/generate_from_upload_sync`

## 这组接口解决什么问题

它负责把 URL、本地音视频或本地文字稿变成一个任务，而不是立刻返回最终笔记。

## 输入方式

- URL 输入走 JSON 请求体，使用 `POST /api/generate`
- 本地音视频走 `multipart/form-data`，使用 `POST /api/generate_from_upload`，并传 `source_type=audio` 或 `source_type=video`
- 本地文字稿同样走 `multipart/form-data`，传 `source_type=transcript`，后端会直接跳过 STT

## 调用后的下一步

1. 从响应里拿到 `task_id`
2. 去轮询任务状态
3. 任务完成后保存或读取笔记记录

字段细节、可选参数和 schema 一律看 Swagger。
