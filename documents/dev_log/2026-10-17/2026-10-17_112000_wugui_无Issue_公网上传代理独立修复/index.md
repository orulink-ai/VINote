# 公网上传代理独立修复

- 2026-10-17，Asia/Shanghai；作者 wugui，实施 Codex；主线程负责实际服务器与 UI 验收。
- 新增标准库 host Nginx 脚本及 focused 测试/说明。默认 dry-run、显式路径/binary，执行需原 SHA256；克隆唯一 prefix 为专用 exact 上传路由，原 prefix 和其它路由字节保留。已足够的限额 no-op，不执行 reload。
- 没有修改产品 Python、原 deploy/workspace 脚本、镜像、环境、卷、网络或主线程实际验收文档。历史 edge container 路径未作为默认值；使用主线程明确核验的 BaoTa host 参数。
- 实现后离线专项首轮 27 passed；追加冲突路由和原子替换后 IO 失败回滚后 29 passed，0.20s。所有 Nginx 命令是离线 fake；未调用实际服务或模型/识别。脚本已冻结，SHA256 见 docs/content-upload-proxy.md。
- 原配置独占 0600 字节备份和 SHA、加载文件校验、原子替换、失败恢复/重载及无法回滚时的人工处理回执均覆盖。仅 headers 无凭证验收与真实部署由主线程后续记录，不能提前声称通过。
