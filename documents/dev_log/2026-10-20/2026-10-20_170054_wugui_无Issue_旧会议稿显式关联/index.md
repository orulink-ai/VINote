# 旧会议稿显式关联原录制

- 创建：2026-10-20 17:00 +08:00；作者：wugui / Codex。
- 分支：codex/meeting-delivery-formats-connections；本地实施，未提交。
- 用户要求：当前owner明确确认旧稿对应canonical原录音/录屏；仅影响展示归组，不能改task_id、源产物、正文或扩大播放/生成权限。与[会议多形态任务](../2026-10-20_161206_wugui_无Issue_会议多形态与飞书归组/index.md)并行集成。
- 独立写集：models/services/routers的meeting_source_link新模块及专用测试；不修改note_library主模块、main路由注册或db初始化，交主线程集成。
- 设计：owner/note唯一不可变关联，创建CAS revision=0；同目标/hash幂等，不能覆盖其他人工或可信产物关系。目标原件必须owner/UUID/meeting workflow/contained regular media/hash核验。读取只投影，不授权文件访问。
- 录制时间：复用主线程即将提供的meeting_recording_metadata只读helper；缺失为null，不猜标题/mtime/生成时间。
- 验证计划：真实临时DB及文件，账号/团队/UUID/已有关联/CAS/同大小篡改/符号链接/一跳canonical/不写源产物反例；不云调用不推理。

## 实施与验证（2026-10-20 17:10 +08:00）

- 新接口：`GET /api/meeting-source-links/targets`、`GET /{note_id}`、`PUT /{note_id}`；PUT `{confirmed:true,canonical_task_id,source_version,expected_revision:0}`。响应带revision、source_version、association_kind和meeting_source（owner/canonical/recording_started_at）。接口限desktop Cookie账号；云运行时或Bearer请求拒绝。
- 主线程已注册model/router，并保留原 `_with_meeting_source` artifact-only；新增 `_with_meeting_display_source` 只用于客户端response，优先可信产物，再按desktop/personal调用本模块project。已补集成反例：manual wrapper可归组、artifact helper仍None、原task_id/media_kind不变、其他owner与非desktop无fallback。未修改主线程拥有的note_library/main/db文件。
- GET目标只读取声明hash/正规原件可用性，PUT提交时真正流式重算SHA256，记录前再次核对元数据及文件身份；无自动修复/复制/删除原件。DB并发通过SQLite BEGIN IMMEDIATE／其他数据库note行锁和唯一键保障，冲突不覆盖。初次revision0，同一绑定/hash重复确认幂等；已有关联不支持改绑。
- 时间复用 `recording_started_at(request_document)`，返回带offset的ISO；兼容display_name明确标UTC。已直接协调UI agent忽略display_name并按用户时区格式化，缺失时间保持未记录+短ID消歧。
- TDD：先写单项“只保存关联且幂等、不改正文/task/产物”测试，对service NotImplementedError红；实现后通过。补安全反例过程中真实Windows path stat与CRT fstat的ctime语义差异导致正常文件拒绝，已改用可比的文件身份/size/write-time（POSIX仍带ctime），未删除symlink与hash保护。
- `pytest tests/test_meeting_source_link.py tests/test_meeting_recording_metadata.py -q --maxfail=2` **50 passed**（本模块35 + 主线程metadata15）；Windows真实symlink四项无skip、hardlink、同大小篡改、两worker冲突、核验中owner/可信关系变化均通过。最后添加desktop guard后，受影响router/时间/wrapper三项重新运行 **3 passed**；`git diff --check`通过。仅既有Starlette deprecation warning。
- 本模块源码及测试冻结，未提交、未调用真实归档API、未关联真实旧稿、未云调用/推理。主线程继续UI与真实桌面验收，不能将此离线结果冒充实际归档完成。
