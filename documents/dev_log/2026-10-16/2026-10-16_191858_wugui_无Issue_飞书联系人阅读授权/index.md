# 飞书联系人阅读授权与未知授权恢复

- 作者：wugui / Codex；2026-10-16，Asia/Shanghai。
- 授权范围：根 Feishu service/routes、最小helper与离线测试/合同；不改schema、认证、原件、ASR或scope，不提交/部署，不外部创建/发送。
- 原问题：新private文档的联系人只核验既有权限；旧群授权超时被记为普通failed，显式重试会再次grant。只读调查用真实process+mock复现两次grant；没有外部请求。
- 实现：新显式policy和status协议，原请求/版本/snapshot冻结；所选对象view授权前durable granting；未知只读核验，消息unknown不重发；旧联系人不追加授权。新增verify-permissions内部核验路由不排worker。修正目标临时不可用被误报403，机器人消息标题改通用。
- 精确补丁基线由主代理保存在 `data/feishu-repair-20261016/backend-baseline`；保留工作区他人修改。

## TDD与证据

- Red：新增focused测试首次运行11 failed、1 passed，失败包括未实现policy参数、status协议、群grant重放及目标502误报403。
- 第一轮Green：新增12 passed；扩展中断、持久化失败、owner/连接、恢复路由、消息/正文unknown反例。
- 首轮8文件回归211 passed、6 failed：4处旧群读回失败断言需更新为保守permission_unknown；2处全socket封锁影响Windows内部socketpair，后续保留内部loopback并禁止外网。该轮不记完整通过。
- 新focused路由测试曾误用未替换的router session_scope而返回404；已改为临时DB，不作为生产故障结论。
- 最终测试、源码hash与精确部署包见本档案后续追加及 `data/feishu-repair-20261016/backend-result`，完成前不宣称已部署或送达。

## 边界与后续

正常创建/授权/通知在mock中验证，真实租户创建、组织策略和机器人可达性待主代理授权验收。部署对象为VINote integration workspace，VILab不变。单worker既有owner锁/DB租约边界保留，不宣称跨副本调度保证。

历史背景：[会议工作台与飞书交付](../../2026-10-10/2026-10-10_202442_wugui_无Issue_会议工作台与飞书交付/index.md)；当前无跨设备同步，local_snapshot新发布合同不由本任务修改客户端。

## 最终离线结果

8文件247 passed（含新增focused42），1现有Starlettewarning。共享TS合同严格tsc与实际Node运行通过。新增历史unknown/result_unknown无batch反例先失败，补单条件后最终全通过。三runtime源码再次冻结，精确基线patch在隔离副本check/apply及LF字节hash一致。完整manifest、SHA256SUMS、source.patch、payload.tar.gz与REPORT.md保存在data/feishu-repair-20261016/backend-result。未提交、部署或外部写入。
