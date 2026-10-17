# 公网上传代理的独立修复

`deploy/content/enable-upload-route.py` 是独立的宿主机 Nginx 运维脚本，只使用 Python 标准库；不改产品 Python、镜像或原 workspace 配置脚本。用于检查并修复历史小上传限额残留，不能假设旧部署文档中的路径仍然生效。

主线程本轮已确认 BaoTa 宿主机配置如下，脚本仍要求显式指定并核验：

```bash
sudo python3 enable-upload-route.py \
  --config /www/server/panel/vhost/nginx/supabase-vinote.orulink.ai.conf \
  --nginx-bin /www/server/nginx/sbin/nginx
```

默认 dry-run 不写文件、不运行 Nginx。审核 JSON 的 `action`、`original_sha256`、`effective_body_limit_bytes` 和 `candidate_sha256`；限额已达到 129 MiB 或无限制时 no-op，不 reload。继承来源不可确定、目标不唯一、存在不同的上传路由/转发/鉴权规则时拒绝修改。

执行时追加以下参数，散列必须来自刚审核的原配置：

```text
--execute --expected-sha256 ORIGINAL_SHA256_FROM_DRY_RUN
```

脚本从唯一的 `location ^~ /vinote-api/` 克隆一个 `location = /vinote-api/api/generate_from_upload`。仅专用路由使用 `client_max_body_size 129m`（128 MiB 文件加 1 MiB multipart 预算）和 `proxy_request_buffering off`；其余 rewrite、上游、限流、Host/Authorization/Forwarded-Proto、超时与响应缓冲指令保留，原 prefix 及其他路由逐字不变。

执行要求 POSIX。使用同目录 advisory lock；先以指定 binary 的 `-T` 核对目标文件确实被加载，再保存原配置字节的独占 0600 备份，备份名称和回执含原 SHA256。候选文件原子替换并保留原 uid/gid/mode；经 `-t` 和加载内容核验后才执行 `-s reload`。不能依靠此锁阻止其它管理员手工改文件，因此检测到并发修改时拒绝覆盖并明确报告人工处理。

校验或 reload 失败时，恢复原字节并再次校验、加载核验和 reload；回执分别报告 `bytes_restored`、`rolled_back`。回滚重载失败会标记 `rollback_requires_attention`，不能当成成功。备份保留供人工恢复；不会自动清理。不会输出 `nginx -T` 内容或替换其它 host/auth 配置。

脚本 SHA256：`e00f10cf4a1c97859e81903e3d127897f387cbaa6268dd23bccef776c0142534`。

本代理离线专项 29 项通过：字节/CRLF 保留、引号/注释、限额继承及 no-op、冲突失败关闭、原字节备份、校验/重载/原子替换后失败回滚、并发修改保护和默认 dry-run。未执行服务器操作、上传或 ASR/LLM 调用。主线程后续另记实际代理回执；无凭证仅 headers 的 401 可证明到达后端鉴权，不代表实际大文件或识别验收成功。
