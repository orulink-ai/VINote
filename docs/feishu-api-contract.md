# 飞书位置、权限与交付 API 契约

## 2026-10-16 显式阅读授权与未知结果核验

仅新发布可携带 `recipient_access_policy: "grant_view_and_notify"`，要求手动确认及 operation_id；提交前核验实际服务 `/status` 的 `recipient_access_protocol === 1`，桌面 proxy 同样校验远端协议。该能力字段表示协议支持，不证明应用权限、具体文档可授权或机器人可送达。未传 groups/notify_self 时新 policy 不继承偏好中的通知对象。只处理本次选中的联系人和群，不修改组织、公开链接或应用 scope，不授予 edit/full_access，也不降低已有角色。

policy 参与原请求 fingerprint 和内容 revision，并冻结在 snapshot；历史无 policy 的联系人任务仍只核验已有权限，不能通过恢复追加授权意图。旧群合同原本包含 view 授权，补充派发前的 durable journal 以禁止未知授权重放。新/旧操作仍 owner、Origin、原应用/连接及原文档绑定，无 schema/auth 变更。

recipient 的 `reading_permission.status` 为 `granting | unknown | verified | failed | unverified`；授权派发前先持久化 granting，之后必须 GET 读回确认。未确认时 recipient.status、job.phase/error_code 为 `permission_unknown`；正文/消息 unknown 的 job.phase=`unknown` 优先。普通 retry/resume 不执行未知授权。已有 view/edit/full_access 均直接核验使用；新增协作者使用 `perm=view`、`need_notification=false`，确认可读后才调用既有机器人消息。消息标题统一“文档链接通知”。

`POST /api/feishu/deliveries/{job_id}/verify-permissions`（无请求体，亦可传 `{}`）返回原 owner 的完整 Delivery 并设置 no-store。它仅核验原未知授权：飞书业务调用只有权限 GET，允许既有凭据机制正常续期；只更新内部核验证据，不新建/写正文、不 grant、不发消息、不排 worker。核验到既有直接协作者阅读角色后，recipient 变 pending/reading_permission.verified，job 通常仍 failed/partial_success，等待用户明确继续通知；没有证据或读取失败仍 permission_unknown。另有消息或正文 unknown 时继续保持 unknown，不能因 ACL 可读而解锁。

客户端按钮应为“核验阅读权限”，之后显式“继续通知”；不得把执行通知称为只查询。正常初次确认文案需说明创建文档、向所选联系人/群授予阅读权限并通知，群成员按飞书规则访问，通知失败仍保留文档及已授予权限。旧unknown不得补 policy 或随机更换operation。

`/destinations/check` 的失败增加实际 `http_status`/`uncertain` 证据，enqueue保留原401/502/503等分类，不再全部改为403；这不构成 not_dispatched/安全重试协议。

共享合成fixture：`tests/fixtures/feishu_recipient_access_contract.json`；Python回归核对实际响应，`tests/contracts/feishuRecipientAccess.contract.ts`验证客户端语义类型。它不替代两端真实应用的tsc/实机验收。部署必须包含 feishu_service.py、feishu.py 和新增 feishu_recipient_access.py，更新 VINote integration workspace 服务；不是 VILab ASR 服务更新。本轮不部署、不外部写入。

2026-10-11；供桌面/Web、App 和集成服务共同对接。代码已实现、仅静态语法检查；尚未运行回归测试或真实租户端到端验收。

## 认证和兼容

前缀 `/api/feishu`。除既有 OAuth callback 外，沿用已验证 VINote Cookie 或 Supabase Bearer 身份；客户端不持有飞书凭证。桌面既有共享服务 proxy 保持。

原有 `status`、`recipients`、文档分批检查点和创建未知恢复入口保留。新增发布能力不能仅由 `configured` 或 `connected` 推断。

## 目标结构

```ts
type Destination =
  | { kind: "personal" }
  | { kind: "folder"; folder_token: string }
  | { kind: "wiki"; space_id: string; node_token: string };
type PermissionPolicy = "private" | "inherit";
```

`node_token` 指选中的父节点。知识库空间本身不可直接作为发布目标，进入空间选择具体实体父节点。标识只允许字母、数字、下划线、连字符；不要把 URL 放入 token 字段。个人默认 `private`；文件夹/知识库只接受 `inherit`，不提供虚假的缩窄继承权限选项。

## GET /status

保留 `configured/connected/expired/name/notify_self/groups/auto_publish/destination`；`destination` 为类型字符串。新增：

```ts
{
  destination_config: Destination;
  permission_policy: PermissionPolicy;
  tenant_key: string;
  capabilities: {
    personal: boolean; folder: boolean; wiki: boolean;
    update_existing: false;
    background_delivery: false;
    resume_pending: boolean;
    organization_wide_sharing: false;
    recipient_edit_permission: false;
  };
  capability_reason: string;
}
```

personal/folder/wiki 基于有效本地连接及实际 OAuth 授予 scope，代表接口准入条件，不保证具体目标可写；选定目标后再调用 check。未配置、未授权、授权过期或无 scope 证据时返回 false。管理员配置的 `FEISHU_SCOPES` 不作为已获用户授权的证据。尚无持续后台调度、外部编辑冲突检测及原链接更新能力。

## GET /destinations

Query：`kind=folder|wiki`（默认 folder），可选 `folder_token`、`space_id`、`parent_node_token`、`page_token`。

返回 `{items: DestinationItem[], has_more:boolean, page_token:string}`：

- folder 项：`{kind:"folder",folder_token,name,can_create:false,permission_state:"unchecked"}`。未传 folder_token 时列用户云空间根目录中的文件夹。
- wiki 空间项：`{kind:"wiki",space_id,node_token:"",name,has_child:true,can_create:false,permission_state:"unchecked"}`。
- wiki 节点项：同上但含实际 node_token；传 space_id 列空间节点，另传 parent_node_token 列该节点的子节点。

列表可见不等于创建权限。空 items 且 has_more=true 时必须继续分页。文件夹分页字段已由 provider 的 next_page_token 统一为 page_token。选择器还应允许直接输入文件夹 token，因为共享文件夹不保证出现在个人根列表。

## POST /destinations/check

Body 为 Destination。只读检查，不创建探测文档、不发消息。

```ts
type DestinationCheck = Destination & {
  name: string;
  path: string[];
  path_complete: boolean;
  tenant_key: string;
  can_create: boolean;
  can_attempt_create: boolean;
  permission_state: "unchecked" | "allowed" | "unknown" | "scope_missing" | "denied" | "unavailable";
  reason: string;
  error_code: string;
  checked_at: number; // Unix 秒
  identity: "user";
  public_permission?: Record<string, unknown>;
};
```

只有 can_attempt_create=true 才能保存/提交该目标。个人检查用户文档创建/编辑 scope；知识库检查节点空间归属、实体类型、wiki/edit 权限及创建/编辑 scope。实际创建仍可能因权限变化、空间策略而失败。

**文件夹重要区别**：官方元数据可读不证明可创建；已授权且可读时返回 `can_create:false,can_attempt_create:true,permission_state:"unknown",error_code:"create_permission_unverified"`，UI 文案为“目录可读，创建权限将在提交时核验”。不得调用未在官方 auth API 支持列表中的 `type=folder`。

path_complete=false 时仅显示已核验路径片段。文件夹元数据只返回数字 parentId，当前不伪造完整祖先路径；知识库尽力读取祖先和空间名，不能读取时保持不完整。

## PUT /preferences

```json
{
  "notify_self": true,
  "groups": ["oc_example"],
  "auto_publish": false,
  "destination_config": {"kind":"folder","folder_token":"fldExample"},
  "permission_policy": "inherit"
}
```

groups 最多 20 个，去重并验证当前用户与机器人均在群内。返回与 status 相同的结构。auto_publish 默认关闭。旧客户端省略 destination_config/permission_policy 时保留已有目标配置。已有三个旧字段仍按 PUT 全量提交。显式目标支持无通知对象的文档发布；不会因选择组织目标自动扩大到全组织分享。

## POST /deliveries

```ts
{
  note_key: string; title?: string; content?: string; automatic?: boolean;
  destination_config?: Destination;
  permission_policy?: PermissionPolicy;
  notify_self?: boolean;
  groups?: string[];
  version_id?: string;
  revision_id?: string;
}
```

省略目标/通知选项时沿用偏好；显式 `notify_self:false,groups:[]` 仅发布文档。

**2026-10-11 版本绑定修订（覆盖早期消息中的临时标签契约）**：

- `version_id` 必须取自当前账号该笔记的 workspace `versions[].id`，不能传本地展示名如“v1”。
- `revision_id` 必须是 `String(workspace.revision)`，十进制正整数字符串；不能传 updated_at。它表示选择版本时观察到的**整条同步记录的 revision**，用于并发核验；不声称是历史版本最初产生时的 revision。
- 带 version_id 必须带 revision_id。只有 revision_id 时选择服务端当前正文。版本通过 `(owner,note_key,version_id)` 读取，笔记通过 `(owner,note_key)` 读取。跨 owner/笔记、缺失版本、回收站内容与 revision 冲突均拒绝，不回退客户端正文。
- 已同步发布推荐只传 `note_key/version_id/revision_id`；title/content 可省略，实际发布正文从服务端读取。如同时提供 title/content，必须与所选已保存内容精确一致，否则 409。不得临时拼接逐字稿并仍宣称是该版本；需先保存同步为明确版本。
- 未带引用且 owner 下尚无同 key 的 workspace 记录时，继续接受旧本地 `title/content`，但明确 `content_source.kind=local_snapshot,verified=false`，不附服务端版本标签。
- 未带引用但该 owner 下同 key 已同步时，校验客户端正文与服务端当前内容匹配，再自动绑定服务端当前内容。不能借省略引用发布同 key 未保存的编辑。
- 读取与网络预检之后，在提交发布快照前再次核验 workspace revision；并发修改/删除需刷新确认。入队后保存不可变标题/正文，后续 retry 不再跟随 workspace 的新编辑。

例如读取记录得到 `revision:7`，选中 `versions[].id:"current-3"`，应发 `{note_key,version_id:"current-3",revision_id:"7"}`。服务端读取 current-3 的历史正文，并核验整条记录仍处于 revision 7。

幂等：旧请求保留标题/正文哈希；增强请求把目标、权限、通知对象、版本/修订及连接标识纳入幂等键。同请求重试复用同一文档与检查点。自动首次交付复用该 note_key 已有记录。修改偏好不会改变已入队任务的内容、位置、接收对象。仍是 `publication_mode:"new_document"`，不覆盖外部已编辑文档。

返回 Delivery；automatic=true 但未开启自动交付时可返回 null。由当前请求的后台任务处理，进程中断后通过手动 retry 恢复；没有持续队列调度器。

## 交付响应与恢复

`GET /deliveries/{note_key}` 返回最近 Delivery 或 null。

```ts
type Delivery = {
  id: string;
  status: "queued" | "processing" | "failed" | "completed"; // 原兼容字段
  phase: "awaiting_authorization" | "pending_create" | "writing"
    | "setting_permissions" | "notifying" | "partial_success"
    | "completed" | "unknown" | "failed";
  document_url: string;
  needs_document_recovery: boolean;
  error: string;
  error_code: string;
  revision: string; // 幂等哈希，不再一律等于正文哈希
  content_revision: string; // SHA256(title + "\n" + content)
  version_id: string | null;
  revision_id: string | null;
  content_source: {
    kind: "workspace" | "local_snapshot" | "legacy_unverified";
    verified: boolean;
    note_key?: string;
    version_id?: string | null;
    revision_id?: string | null;
    captured_at?: number;
    revision_semantics?: "observed_workspace_revision";
  };
  destination: Destination | DestinationCheck; // 入队目标快照
  permission: {
    status: "pending" | "verified" | "failed" | "legacy_unverified";
    policy?: PermissionPolicy;
    actual?: Record<string, unknown>;
    access_scope?: "owner_and_selected_recipients" | "inherited";
    note?: string;
    error?: string;
    error_code?: string;
  };
  recipients: Record<string, {
    name: string;
    status: "pending" | "sending" | "sent" | "failed" | "unknown";
    message_id?: string;
    error?: string;
    error_code?: string;
    permission_granted?: boolean;
  }>;
  publication_mode: "new_document";
  execution_location: "server";
};
```

文档创建/正文完成、权限确认与消息发送必须分别显示。部分通知失败保留旧 status=failed，phase=partial_success。legacy_unverified 表示兼容旧流程、没有新增权限读回证明，不能展示为已核验私有。

content_source 是独立的内容来源证明。旧交付缺少证明时返回 legacy_unverified，顶层 version_id/revision_id 为 null，机器人卡片不展示未经验证的旧标签。local_snapshot 的正文已由交付表持久保存，但不代表已进入 workspace 同步版本库。

增强发布在上传正文前设置个人私有权限并读回，或读取继承权限。私有关闭链接/组织外分享；组织位置保持继承。群消息前检查共同群成员资格并读取群阅读权限；未确认不发送。消息标题、摘要与版本标签均来自冻结快照。

`POST /deliveries/{job_id}/retry` 可无 body 或 `{ "recipients": ["oc_example"] }`。仅可选择任务已有接收对象。sent 永不重发；sending 中断和未知发送结果转 unknown，不因稳定 UUID 就假设可以无限期安全重发。消息 unknown 当前需在飞书人工核验，尚无消息结果确认 API。

`POST /deliveries/{job_id}/document` body `{ "url":"https://公司.feishu.cn/wiki/节点token" }`：仅创建未知且租约已释放的任务可恢复。同公司、标题匹配、正文为空；文件夹任务核验文档仍在原 folder_token；wiki 核验原空间、父节点、实体 Docx。个人仍接受原 docx 链接。跨目标、非空或无权限不接受。未知创建不会自动重建。

断开连接保留交付历史，但撤销旧连接标识对应任务的后续发送授权。重新授权同一账号并不自动恢复断开前待发任务；增强手动发布形成新连接下的幂等键。普通授权刷新保留连接标识。

## POST /deliveries/resume（有界恢复）

可无 body 或 `{ "limit": 3 }`，范围 1–5。认证后仅扫描当前 owner 最多 100 个 queued/processing 记录，跳过租约仍有效的任务。返回：

```json
{"scheduled":["job-id"],"needs_attention":["unknown-job-id"],"background_delivery":false,"scan_limit":100}
```

scheduled 表示已安排到本次请求的后台任务，不代表已完成；按现有状态接口跟踪。任务串行执行，每个仍需原 DB 租约竞争；重复恢复不会重复已完成任务。

创建未知、发送中断/未知、正文写入中断，以及原连接已撤销或缺少连接快照的任务进入 needs_attention，不自动回放副作用。failed 记录仍走用户显式单条 retry。当前没有常驻扫描线程、无限循环或自动重新发送；`background_delivery:false` 保持。客户端可在明确恢复动作中调用，不应标为持续后台自动交付已支持。

## 原链接更新及持续调度的最小后续方案

- **原链接更新**：先持久记录原文档 token、上次写入后的飞书 revision/受管理 block 范围和 VINote 修订。更新前读取并比较远端 revision，外部编辑进入 conflict，不能直接覆盖；新正文、旧正文备份和每步操作 ID 必须先持久化。替换应使用官方支持的修订条件和稳定操作标识，并在部分写入/超时后核验远端状态再继续。未具备该协议前保持 `update_existing:false`，现有创建流程不用于覆盖。
- **持续调度**：由父 agent 在受控集成服务生命周期中注册单一受管理 worker，分页读取到期持久任务、设置下次执行时间/有限退避/停止条件，复用 DB 租约及当前连接授权校验。进程退出需停止扫描，网络/速率错误有限重试，未知副作用进入待核验。自动首次发布需对接服务端已保存完成事件，而不是依赖客户端一直前台。当前仅实现有界恢复选择与单任务处理，不在业务 service 导入时启动线程；`background_delivery:false`。

## 错误码和 UI 动作

| error_code | 推荐处理 |
| --- | --- |
| not_configured / app_unavailable / app_scope_missing | 管理员配置/发布应用或开通 scope，不无限重复登录 |
| authorization_required / user_scope_missing | 重新连接或补授用户权限 |
| permission_denied / policy_restricted | 检查目录/知识库/文档权限及组织策略，改选目标 |
| target_unavailable / destination_mismatch | 刷新位置或核验恢复链接 |
| create_permission_unverified | 文件夹只读预检限制，允许显式创建时核验 |
| permission_unverified / permission_mismatch | 保留文档；权限未确认，不宣布发布可读 |
| recipient_unavailable / recipient_permission_unverified / recipient_failed | 按失败对象修复资格/阅读权限后重试 |
| create_unknown / message_unknown / result_unknown | 外部结果需核验，不盲目重建/重发 |
| connection_changed | 原连接授权已撤销或身份变化，新的增强手动发布重新确认 |
| rate_limited / provider_error / interrupted | 保留输入及检查点，按阶段重试 |
| invalid_destination / unsupported_permission / invalid_recipient | 修正输入 |
| workspace_reference_not_found | 先同步，再读取当前账号该笔记的真实版本列表 |
| invalid_workspace_revision | 使用 String(workspace.revision)，不要使用本地版本展示名或更新时间 |
| workspace_revision_conflict / workspace_content_mismatch | 保留本地编辑，刷新或先保存同步，再重新确认发布 |
| workspace_deleted / empty_workspace_content / local_content_required | 恢复笔记、选择有正文的版本，或补齐本地快照内容 |

HTTP 失败保持兼容的 `detail:string`；check 和交付状态携带结构化 error_code。invalid body 通常 422；权限拒绝 403、授权失效 401、资源缺失 404；预检拒绝提交可为 403。不要用 HTTP status 代替阶段错误码。

## 数据库整合与验证边界

管理员需按启用功能配置并实际取得用户授权 scope，现有默认 FEISHU_SCOPES 不足以覆盖所有增强操作。常用组合为原有 offline_access/docx:document/im:chat:readonly，加目录所需 drive:drive 或对应细粒度读取 scope，知识库所需 wiki:wiki 或 node/space 的创建、读取、列表 scope，以及 docs:permission.member:auth、docs:permission.member:retrieve、docs:permission.member:create。私有设置/读回需要 docx:document 或相应 permission.setting scope。机器人仍单独需要应用身份 im:message:send_as_bot；它不代替用户授权。应按实际启用的功能与官方 API 文档申请最少权限，并完成管理员审批。

模型 `app.models.feishu_destination.FeishuDeliveryDestinationDB`，新表 `feishu_delivery_destinations`：delivery_id 外键主键、snapshot JSON 文本、phase、permission JSON 文本、error_code。父 agent 负责在 init_db/create_all 前注册；不会给 existing feishu_deliveries 增列。偏好扩展已有 JSON。未触碰 db_models/config/__init__。

已有与新增测试位于 `tests/test_feishu_delivery.py`，需父 agent 串行运行。当前仅 AST parse；没有调用真实文档创建/权限修改/群消息，没有构建、测试执行或进程操作。已实现 owner 绑定的 workspace 引用/正文核验及并发复查，仍待父 agent 串行运行新增用例；真实租户验收、完整路径覆盖、同链接更新及持续后台调度不能声称通过。

## 已核验官方接口证据

- [创建 Docx（folder_token、1770039/1770040）](https://open.feishu.cn/document/server-docs/docs/docs/docx-v1/document/create.md)
- [文件夹元数据](https://open.feishu.cn/document/server-docs/docs/drive-v1/folder/get-folder-meta.md)
- [文件夹列表及 next_page_token](https://open.feishu.cn/document/server-docs/docs/drive-v1/folder/list.md)
- [创建知识节点及父节点容器编辑权限](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/create.md)
- [知识节点信息](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/get_node.md)
- [知识空间列表](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space/list.md)
- [知识节点列表](https://open.feishu.cn/document/server-docs/docs/wiki-v2/space-node/list.md)
- [判断当前身份权限](https://open.feishu.cn/document/server-docs/docs/permission/permission-member/auth.md)
- [读取公共权限](https://open.feishu.cn/document/server-docs/docs/permission/permission-public/get-2.md)
- [增量更新公共权限](https://open.feishu.cn/document/server-docs/docs/permission/permission-public/patch-2.md)
- [协作者列表](https://open.feishu.cn/document/server-docs/docs/permission/permission-member/list.md)
- [增加协作者](https://open.feishu.cn/document/server-docs/docs/permission/permission-member/create.md)
- [通用错误码](https://open.feishu.cn/document/ukTMukTMukTM/ugjM14COyUjL4ITN.md)
