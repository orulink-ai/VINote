# VILab-server 服务端修复合并与公网部署回执

2026-10-16，用户明确要求新建服务端功能分支、合并并部署对应公网服务。

## Git 与发布边界

- 仓库：`orulink-ai/VILab-server`。
- 汇总分支：`codex/asr-long-audio-release-20261016`。
- PR：https://github.com/orulink-ai/VILab-server/pull/147 ，已合并至 `dev`。
- 合并提交：`f41e36ece3d0df2d103029671f5043ba02273056`。
- 分支、远端 dev 和本地 HEAD 已对齐；服务端工作区干净。
- 保留 dev 的既有通知工作流。未提交 VINote 根仓库或 App 的混合未提交改动。
- 设备后端、桌面 UI、App JS 不通过此次服务器部署更新；取消的跨设备同步没有恢复。

## 验证

- PR 的 `Verify server and SDK`、`Build linux/amd64 image`、`forward-event` 全部成功。
- 本机 build metadata 3 项、诊断快照 4 项、发布助手 6 项通过。
- 合并提交在 AWS Linux 隔离环境重新运行 8 组测试：143 passed、1 live ignored。
- 两个上传心跳 loopback WebSocket 测试明确通过；live provider 测试未启用。
- Docker 构建限制 1 CPU / 3GiB、network none；Cargo offline / locked / jobs=1。
- 构建完整源码清单与最终 Git 提交及已验收 7f 源码相同；源摘要
  `[私有摘要已省略]`。
- 此次发布没有发起 ASR 或 LLM 请求。

## 实际部署

- 目标：AWS 香港 `i-0a7dd18ac33563b0c`，公网 `https://api.orulink.ai`。
- 服务：`vilab-server-v040-vilab-server-1`；没有调用 VM206 部署工作流。
- 新镜像：`sha256:4194689518ab611417d9957fd1254991adea6841213a693ac3e30645cca2cfff`。
- 精确回滚镜像：`sha256:cf2cc99465098f4c917cfdbdbd034c8551f2d728ac1f66dac10dba3e6b06175d`，保留未删除。
- 切换前保存 305 条允许列表 provider 诊断；独立 route 投影为 0 条，不代表无历史请求。
- 三次当前服务网络命名空间连接观察后通过原维护守卫。全局任务数仍未知，没有伪填空闲。
- 单服务切换成功；配置、挂载及权限相关完整投影不变量一致。
- 外部 HTTPS `/health` 实读：commit 为上述合并提交，`dirty=false`，版本字段 `0.4.0`。
- 使用当前 VINote 账号读取公网 `/v1/models` 返回 200：4 个模型、2 个 ASR；两者
  `recordedAudio` 为 protocol=1、adaptive_pause、2097152 bytes、service_budget。
  这是输入预算声明，不是模型时长上限。

远端回执目录：

- `/home/ubuntu/vinote-review-20261016-f41e36e`：测试、二进制、构建和缓存来源回执。
- `/home/ubuntu/vinote-deploy-20261016-f41e36e`：状态、诊断、观察、维护审查、切换回执。

## 实测边界

本次证明修复已经进入 dev 并运行在对应公网服务器，不能代替新的两端长录音验收。
桌面端和 App 热更新端口 3100 / 8900 / 8081 保持运行。已关闭本轮临时源码传输页及
其独立 HTTP 进程；没有停止开发服务、清理原始文件、修改模型配置或用户权限。
