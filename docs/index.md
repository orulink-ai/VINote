---
layout: home

hero:
  name: "VINote 文档"
  text: "面向使用和接入，而不是重复抄一遍 Swagger。"
  tagline: "这里负责讲清楚工作流、认证、集成和部署。字段级接口定义继续以 FastAPI OpenAPI 为准。"
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quickstart
    - theme: alt
      text: API 概览
      link: /api/
    - theme: alt
      text: 打开 Swagger
      link: http://127.0.0.1:8900/docs

features:
  - title: 先讲工作流
    details: "先回答怎么用：登录、提交 URL 或上传本地音视频 / 文字稿、轮询任务、保存笔记、继续编辑。"
  - title: 不重复造轮子
    details: "本网站负责使用说明，Swagger 和 ReDoc 继续负责接口结构、字段规则和在线调试。"
  - title: 面向集成
    details: "把 MCP、部署、认证方式和路由分组组织成开发者真正会关心的入口。"
---

## 信息架构

这套文档站负责回答 Swagger 不擅长回答的问题：

- VINote 是什么
- 用户工作流是什么，以及 URL / 本地上传 / 文字稿直传分别怎么走
- 认证怎么接
- 不同 API 分组该怎么理解
- MCP 和本地部署怎么接入

Swagger 继续负责：

- request / response schema
- 字段校验和默认值
- OpenAPI 示例
- 在线调试接口

## 推荐阅读顺序

1. [介绍](/guide/introduction)
2. [快速开始](/guide/quickstart)
3. [认证](/guide/authentication)
4. [生成笔记](/api/generate-note)
5. [任务状态](/api/task-status)
6. [已保存笔记](/api/saved-notes)
