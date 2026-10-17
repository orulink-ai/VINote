# 受控公网内容 runtime

- 时间：2026-10-17，Asia/Shanghai；作者 wugui，实施 Codex，部署/App 协作由主线程及 Darwin 负责。
- 目标：在独立候选中实现默认关闭的公网内容能力，受控复用当前生成流水线；不 push、不调用真实模型/ASR、不操作服务器。原运行目录源码未改。
- 本次不是事先完整 Red/Green：实现后补充定向测试。首轮 24 passed/9 failed，暴露当前 Starlette 不支持新版 form 参数；改为锁定依赖兼容写法后 33 passed。后续音频链在 Windows 长 pytest 路径失败，改用短隔离临时路径后真实 mock 音频链通过，没有改 ASR 分段或跳过测试。

## 架构与实现

VINOTE_CONTENT_CLOUD 默认 false，且必须与 workspace_cloud_runtime 同时 true。内容模式不注册设备/local-auth/notes/workspace/sync router，只注册五个受控路径；设备模式新增同协议、受 generation 鉴权的只读 capabilities，避免 App dev 预检禁用整个导入页。

Supabase Bearer 经真实验证接口验证后，复用 issuer/subject 旧绑定或创建新 UUID namespace；新增私有表 content_cloud_identities，属于 additive schema，create_app 导入早于 init_db，继承 RLS/撤销直连权限流程。不按邮箱关联，无 UserDB FK/session/refresh 插入；真实 mock NoteService 链在 FK=ON 的隔离 DB 中验证。

纯 ASGI ContextVar lease 覆盖响应和被等待的 BackgroundTasks，最终撤销；复制 context 共享被撤销的 lease，不存 token/refresh 到任务/回执。VILab gateway 和内容专用 ASR 适配器读取当前账号 lease，不改设备会话刷新路径。进程单提交槽，durable operation 防重，reserved/accepted 均不自动恢复执行。

公网视频链接明确关闭并在能力预检返回 video_url:false；现有多级 downloader 缺少可证明的出口隔离，本轮不冒充安全。普通网页沿用绑定公网 IP/Host/SNI 的提取器。上传媒体在固定 demuxer、file/pipe 协议、MOV 外部引用关闭条件下规范化，超出解码体积限额拒绝而非截断后转写。原件继续在设备。

## 验证与部署边界

先前专项及相邻 generation-auth/app-factory/workspace-bootstrap/task-model-source 回归 84 passed，严格离线，含真实网页/逐字稿/音频 mock 任务链。继续补请求预算测试并使用短绝对 basetemp 最终复验，结果在提交前追加。不重复无差别全后端/前端测试。

主线程新增 deploy/content Dockerfile/Compose overlay 已审阅：只扩展审过的 base image、安装候选 requirements 并 COPY app，overlay 只指定不可变 image 和新增开关。由于实际 server 基线较旧，不能只 COPY 本次八个 Python 文件，必须覆盖同一 HEAD 全部 tracked app Python 并核验依赖。现有环境/卷/网络不应被替换。未运行 Docker 构建或实际部署。

详细路由、COPY 清单、schema 和限制见 docs/cloud-content-runtime.md。没有真实 ASR/LLM 验收；实际部署与回滚证据由主线程后续补充。

## 最终离线验证与交付

- 使用短绝对 basetemp D:/projects/VINote/data/cc-tests-run1，runtime 专项及 generation-auth/app-factory/workspace-bootstrap/task-model-source 共 85 passed，6.58s；内容专项 37 项。纯离线守卫、单进程，外部认证/目录/ASR/LLM 均为 mock。
- VitePress 完整构建 Node 384MB，9.71s 通过。静态 743 文件、228 Python 语法、275 前端导入闭包、已知私人清理值/高置信凭据/禁止产物检查无命中。git diff --check 通过。
- 主线程最后授权将中文提交推送现有 PR52 触发 Docker CI；这不代表实际部署或模型/ASR 实测通过。提交后交由主线程从不可变 HEAD 组装完整 Python 快照及部署 overlay，另补真实验收证据。
