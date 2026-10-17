# ASR 安全错误分类与同模型恢复

2026-10-14。证据分为实际任务失败、源码修复和模拟回归；本次没有发起真实 ASR、修改 App 或修改/重启公网服务。

## 实际失败证据

桌面豆包任务 `[个人标识已省略]` 于 01:45:53 失败。收到的进度为 1686.8 / 1687.046 秒，说话人缓存已完成。异常链最终进入 `asr_stream_service.py` 的 error/session.error 分支，而不是 final 文本校验、客户端超时或 ConnectionClosed 分支。旧实现将该事件转成通用 RuntimeError，所以 non_retryable 只是客户端分类结果，不能证明上游永久失败；进度接近全长也不能证明最终结果成功。

## 本地后端修复

### 公网只读核验补充（02:14）

实际运行容器 `vilab-server-v040-vilab-server-1`，公网失败 session
`[个人标识已省略]`，elapsedMs=1706365。
在服务器端筛选安全字段并与源码固定错误文本精确比较，
`matches_final_timeout_12000ms=true`：已确认为豆包等待最终结果 12000ms 超时。
不是用户录音时长限制，也不是客户端 final 文本校验错误。
此次未输出原始转写或凭证；没有重启容器或改动账号权限。
导致最终结果未及时返回的上游/结束协议原因仍须复验，不能把压缩帧支持改动直接声称为本次根因。

- `ASRServiceError` 仅保留允许的协议 code、UUID session ID、允许的 stage 和末帧发送完成状态。日志及异常不保存原始事件、provider message、转写正文或凭证。未知 code 归为 unknown_error，任意字符串不能进入诊断。
- session.started 中收到的有效 UUID 可关联后续失败。失败日志包含安全字段；转写异常携带同模型尝试记录与诊断。
- 只有服务明确报告的 asr_timeout、asr_stream_failed、rate_limited、asr_rate_limited、service_unavailable、asr_unavailable 进入已有最多三次同模型重试。asr_failed、协议错误、认证/权限/配额错误和未知分类不自动重放。现有连接阶段及明确 HTTP 瞬时失败策略保留。
- 末帧开始发送后断开，或等待最终结果超时，视为 unknown_result；session.completed/cancelled 未返回 final 同样不视为成功、不自动重放。已确认区间及原件保留。
- limit 仅接受严格有限正数，排除 bool、数字字符串、NaN、Inf 和非正值。明确存在但无效的结构化字段不回退到错误文本。仅缺少字段时兼容原有明确 session-limit 文本。Python checkpoint 的 None 继续表示无已知 cap；其他无效缓存在发请求前失败，原缓存不改写。
- 不按 provider/model 名称设置固定分段时长，不改变所选模型。

## 验证与限制

### VILab 结束协议修复准备

独立 VILab 工作树已准备官方 Demo 同路径的非空末包负序号发送、最终帧/关闭处理、
有界 gzip 响应解析及未发送尾音护栏。34 项合成/loopback 测试通过，1 项 live 跳过。
报告位于 `D:/projects/vilab/VILab-server/artifacts/volcengine-protocol-review-20261014/REVIEW.md`。
当前未部署；空 EOF 兼容性与压缩缺口未被证明为本次公网故障的根因。
独立复审发现提前 final 可与末包写入竞争，初版补丁未获准部署；正在补齐
末包写入确认护栏及阻塞写入竞态测试。34 项通过仅为初版测试结果。
02:47 修订版增加 reader 观察时的 EOF 写入状态和音频覆盖护栏，提前 final 不因
后续写入完成变为成功。作者提供 40 项通过、1 项 live 跳过；独立复审待完成，
尚未部署，也未重启正在承载手机长任务的服务。
手机活跃长会话不会因本轮修复而被强制重启，后续需要部署后完整豆包原录音复验。

聚焦命令：`.venv/Scripts/python.exe -B -m pytest tests/test_asr_stream.py tests/test_vilab_transcriber_retry.py -q`。单进程，无重型模型或云调用。覆盖非法结构化值/缓存、缓存保持、错误安全字段、session 关联、末帧后断开不重放、有界同模型重试，以及既有 pacing/final/缓存恢复回归。

03:35 最新 VILab 候选在收到 Binary 帧时、解压解析前冻结发送覆盖，避免解析期间的写入完成把提前 final 提升为成功。46 项合成测试通过，1 项 live 跳过；独立静态复审未发现剩余阻断 P1。尚未 Linux 构建、部署或完成真实豆包长录音复验。App 严格校验与正常核验续期保护已采用，根代码六组 69 项回归和 TypeScript 通过；实际手机长任务仍待新原生安装后重测。

04:14 联合 root 已采用 Aliyun terminal 与 App 安全类别保存修复。根 App 七组81项及 TypeScript 通过；联合服务端 Windows 原树 Aliyun21项、Volcengine过滤42项（1 live忽略）、routes分类5项通过，这些组存在交叉，不能简单相加。原生 App 有声合成38.236秒已完整转写、1个speaker turn、LLM draft/audit、保存并打开正文；不等于四份真实长录音通过。Linux联合包仍未构建/部署。

公网仍运行旧 ASR 服务；联合源码修复尚未 Linux 构建、部署。本地修复不能恢复旧服务已丢弃的分类，豆包 28 分钟最终结果超时仍待部署后复验。App 严格校验与安全类别补丁已经采用并安装，上述 04:14 根代码及实机证据替代早先“仅暂存”的状态。
