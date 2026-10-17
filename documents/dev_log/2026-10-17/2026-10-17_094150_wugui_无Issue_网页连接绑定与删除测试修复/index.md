# 网页连接绑定与删除测试修复

## 基本信息

- 创建时间：2026-10-17 09:41:50，Asia/Shanghai。
- 建档作者：wugui（当前 git config user.name）；实施：Codex。
- 需求：用户授权直接修复根工作区 DNS rebinding P1 和 Notes.delete.test 的 SyncSettings 缺失引用；无 Issue。
- 分支：codex/meeting-workbench-feishu；交付状态：本地修复与定向验证完成，未提交、未合入、未部署。
- 边界：只改网页来源服务及定向测试，不改飞书文件、App 指针、服务或分支，不做云调用；串行单 worker 测试。

## 背景与验收

前序只读检查发现网页域名的公网检查与 HTTP 实际解析脱节，以及删除测试引用不存在的同步页。主线程已确认 fetch 后 origin/main=432ad2490fee8643b3571a1cb4d83d39af0eb6af 最新；本任务不再 fetch。

- [x] 网页实际连接仅使用已验证 IP；原 Host、TLS SNI 和证书校验保留。
- [x] 重定向逐跳验证；混合公私网、IPv6、连接失败不退回域名连接。
- [x] 删除测试覆盖当前设备回收站行为、失败与显式重试、避免重复提交、真实来源返回。
- [x] 定向测试串行通过；记录实际命令、结果与限制，不冒充部署/设备验收。

## 过程记录

- 09:41：读取源码、现有测试、根规则和开发档案规范。初始设计采用已校验 IP URL + 原 Host/SNI，并禁用连接复用，防止同 IP 的不同域名误复用 TLS 身份。使用本机已安装 httpcore 源码核实 sni_hostname 扩展的连接路径，未访问网络。
- 测试策略：先增加网络边界反例并验证旧实现失败，再实现；前端先运行原文件记录缺失模块，再迁移到现有页面契约。
- 实现复核：最终改为每个重定向 hop 单独创建并关闭 HTTPX Client，而非仅设置 max_keepalive_connections=0。这样既不复用同 IP 下旧域名的 TLS 连接，也不让 IP URL 的 Cookie jar 在不同原域名之间传递服务端 Cookie；无需操作 HTTPX 内部连接池或全局 DNS。
- 前端迁移后的第一次运行出现 1 项测试 fixture 错误：vi.resetAllMocks 清空了 mockResolvedValue 设置，录音读取返回 undefined。将 mock 改为带原始 async 实现的 vi.fn 后，三文件全部通过；未为测试修改产品页面。

## 实际文件范围

| 文件 | 变更 |
| --- | --- |
| [document_source_service.py](../../../../app/services/document_source_service.py) | 新增 _public_target：使用 HTTPX 规范化主机名解析，拒绝任一非公网答案和 scoped host；实际 URL 绑定已验证 IP，原 Host/SNI 保留；逐跳独立 Client，失败不回退域名连接。保留 public_url 的验证并返回原 URL 的兼容接口。 |
| [test_document_source_network.py](../../../../tests/test_document_source_network.py) | 新增 14 个离线网络边界用例，使用真实 HTTPX/httpcore HTTP/TLS 请求路径、模拟 DNS 与底层网络流；阻止真实 socket.connect。 |
| [test_document_sources.py](../../../../tests/test_document_sources.py) | 原 HTML 提取测试改为模拟 DNS 公网答案，仍使用 MockTransport；不再绕过已脱离实际连接路径的 public_url。 |
| [Notes.delete.test.tsx](../../../../frontend/src/pages/Notes.delete.test.tsx) | 迁移到现有独立删除按钮及 StorageSettings，保留有效的失败/确认/身份用例，移除旧同步队列与旧菜单断言；共 8 项行为测试。 |
| 本 index.md | 中文 journal、命令、结果、范围和验收边界。 |

没有增加依赖或配置，没有更改路由/API/schema，没有修改 Notes.tsx、StorageSettings.tsx 或飞书代码。不在本任务修复账号专属清理回执问题。

## TDD 与验证

### Red（修改服务前）

根目录执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_document_source_network.py -q -p no:cacheprovider
```

初始 11 项中 **5 failed / 6 passed**。HTTP、HTTPS、相对重定向及 IPv6 的失败显示原域名第二次解析变成 127.0.0.1/::1，fake connect 边界断言阻断；连接失败用例显示实际仍使用域名。这里没有对真实内网发请求。

frontend 目录执行：

```powershell
node node_modules/vitest/vitest.mjs run src/pages/Notes.delete.test.tsx --maxWorkers=1 --no-file-parallelism
```

结果：**1 failed suite，0 collected tests**；Vite 明确报 `Failed to resolve import "./SyncSettings"`。

### Green（最终实现）

根目录执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_document_source_network.py tests/test_document_sources.py -q -p no:cacheprovider
```

最终结果：**23 passed，1.52s**。网络边界 14 项 + 既有文档提取/缓存复用 9 项。覆盖：

- 公网答案后域名变成内网，TCP 仍使用首次已核验 IP（HTTP/HTTPS）；保留请求路径、query 和 Host。
- HTTPS 连接使用原域名 SNI，真实默认 SSLContext 保持 check_hostname=True、CERT_REQUIRED。
- 相对跳转再次解析原主机，发现重绑定后在连接前阻断；显式 loopback、链路本地元数据 IP、IPv6 loopback 重定向同样不连接。
- 同公网 IP 的不同原域名分别建立 TLS 连接，使用各自 SNI；不会携带前一跳 Set-Cookie。
- DNS 公私网混合、IPv4 私网、链路本地、IPv6/mapped loopback 全部拒绝；合法 IPv6 公网地址可被绑定。
- 公网连接失败不使用原域名重试，不自动选择其他目标。

frontend 目录执行：

```powershell
node node_modules/vitest/vitest.mjs run src/pages/Notes.delete.test.tsx src/pages/Notes.actions.test.tsx src/pages/StorageSettings.test.tsx --maxWorkers=1 --no-file-parallelism
```

最终结果：**3 files passed，15 tests passed，5.94s**；其中本次修复文件 8 项。保留笔记不执行删除；只移除确认的对象；映射存在但无正文时使用原 local ID；落盘失败保留目标并只在再次点击后重试；未确认结果不关闭；等待写入期间双击只调用一次且禁用取消；全局保存忙时禁止删除；回收站进入 canonical storage 并恢复归档/项目/anchor。

三个测试文件串行且 maxWorkers=1；没有同时运行后端测试。输出只有相邻既有 React Router v7 future flag 提醒，不是失败。未为消除提醒扩大产品改动。

### 验证边界及遗留

- 本轮没有真实 DNS/TCP/TLS 网络请求；TLS 测试验证真实客户端传入的 SNI 和证书校验配置，模拟底层握手，不代表真实站点证书或网络可用性验收。
- 为保证最小安全实现，每次只连接第一条已验证公网 IP；其失败后报告错误，不退回域名解析或自动切其他地址。多 IP 可用性优化不在本次范围。
- 未执行全仓测试、构建、设备验证、服务重启或飞书实发。已有服务热更新由主线程管理，本任务没有操作其生命周期。
- 两项代码问题已有定向证据；后续由主线程将这五个文件按最终快照纳入追加修复 commit。没有 stage/commit/push/checkout/worktree 或修改 App 指针。

## 变更记录

### 2026-10-17 09:46 Asia/Shanghai｜wugui / Codex

完成上述最小服务修复和旧测试契约迁移，最终后端 23、前端 15 项通过。仅本地修改，未提交或部署；主线程飞书验收与后续交付分支流程继续独立进行。

## 历史关联

延续本轮只读审查的两个具体问题；只读报告在忽略的 data/desktop-readonly-review-20261017/REPORT.md，不作为公开档案证据依赖。本档案直接保存可复查的代码位置、设计与测试结果。未修改其他历史任务档案。
