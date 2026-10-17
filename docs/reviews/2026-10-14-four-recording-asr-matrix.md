# 四份完整会议录音：只读核对与最小交叉测试矩阵

2026-10-14，Asia/Shanghai。本轮仅 GET 模型目录、读已有文件及 ffprobe 元数据；
未发起 ASR/LLM、修改模型偏好、刷新云凭证、修改后端或 reload。凭证仅在内存使用，
未输出或写入文档。手机样本的下列路径是当前桌面保留副本，不证明手机原件仍可读。

## 当前模型目录

使用完成的 50 分钟任务所绑定账号/公网服务 `https://api.orulink.ai`，读取
`GET /v1/models` 返回 200。读取时两项均通过 VINote 当前严格可用性校验。

| 用户选项 | 具体模型 ID | runtimeStatus / availability.status | 能力字段结论 |
| --- | --- | --- | --- |
| Aliyun | `asr:6:aliyun:22:paraformer-realtime-v2` | available / available；retryAt 无值 | 未提供有效 capabilities 对象，未获得模型时长/帧大小能力声明 |
| 豆包（火山 ASR） | `asr:14:volcengine-asr:8:bigmodel` | available / available；retryAt 无值 | 同上；这是目录里的具体 ASR ID，不是通用豆包 LLM 名称 |

available 只证明当前目录准入，不保证本次上游调用或所有未来配置模型成功。已有
火山 120 秒 final 是单独的历史实测，不等于下面两份完整录音通过。客户端使用
统一节流小帧，不按模型名写死分段时长；只在服务明确返回时长错误及有效限制时
调整未完成区间。帧大小/节流/接收超时不是模型时长上限，普通网络失败不切模型。
新增模型必须有真实目录 ID、可用性和适配器支持的服务协议，再以样本验证；未声明
能力保持未知，不能把本次两个模型的结果推广为任意模型保证。

## 原件只读核验

四份文件均存在、可打开读取，ffprobe 成功返回真实音频流/时长；未解码完整音频。
下列秒数来自文件容器，不是墙钟会议时间。

| 样本 | ffprobe 秒数 | 字节数 | 流/容器 | 当前有效原件路径 |
| --- | ---: | ---: | --- | --- |
| Desktop 50:37 | 3036.705669 | 49114564 | AAC，MP4/M4A 家族 | `D:/projects/VINote/output/20261013_224352_VINote-2026-10-10-50m37s-original.m4a/media/source_audio.m4a` |
| Desktop 视频 28:07 | 1687.022426 | 46329916 | H.264 + AAC，实际 MP4 家族 | `D:/projects/VINote/output/20261012_132658_测试｜或宇连接 & 富港北京电子 交流会议/media/source_video.webm` |
| Phone 78:10（桌面副本） | 4690.454059 | 75859409 | AAC，MP4/M4A 家族 | `D:/projects/VINote/output/20261012_133714_测试｜1791772251873-wgvk7e3d2jj/media/source_audio.m4a` |
| Phone 22:57（桌面副本） | 1376.548571 | 22266052 | AAC，MP4/M4A 家族 | `D:/projects/VINote/output/20261012_125852_测试｜1791626494986-b2td8j3349j/media/source_audio.m4a` |

28:07 保留副本后缀为 `.webm`，ffprobe 实际识别为 MP4 家族；本轮没有改名或转码。
三个旧失败任务 request.json 仍引用改名前 UUID 目录，字面路径已过期；对应
source_media.json 的相对路径和当前目录内原件有效。重新导入应使用上表有效路径；
恢复旧 task 必须通过现有 source resolver 和模型确认，不直接重放旧路径。

## 最小矩阵：两份 Aliyun、两份豆包

此分配为交接建议，未切换设置或执行待测项；实际执行前逐项在 native 确认模型并
绑定任务快照。串行运行，每次仅一个云 ASR，保留原件和成功 speaker/ASR 检查点。

| 完整样本 / 流程 | 模型 | 当前证据状态 | 下一项实际验收 |
| --- | --- | --- | --- |
| 50:37 / Desktop | Aliyun | 用户报告 task `[个人标识已省略]` 于 00:53:10 COMPLETE，固定 Aliyun、复用 speaker；随后已 native 保存 note `[个人标识已省略]` | 已完成 native 保存；尾段覆盖与正文人工核对、再次打开/导出分别记证据，不重复云生成 |
| 28:07 MP4 / Desktop | 豆包 `bigmodel` | 原件可用；此前失败是历史结果，尚无本轮完整成功证据 | native 导入/确认该模型，完整 final → speaker → 纪要保存；保留视频原件 |
| 78:10 / Phone | Aliyun | 桌面副本可用；手机本机文件可读及本轮完成待核验 | 手机原件路径/权限核对，明确 Aliyun，完整 final、手机分析检查点、保存后重入；不得以桌面副本接口跑代替手机验收 |
| 22:57 / Phone | 豆包 `bigmodel` | 桌面副本可用；手机本机文件可读及本轮完成待核验 | 手机原件路径/权限核对，明确 bigmodel，完整 final、speaker、保存后重入 |

每份最少记录：实际入口/账号、原件指纹与时长、冻结服务 Origin/模型 ID、task 或
操作 ID、final 覆盖至尾段且无意外空洞/重复、speaker 缓存校验、LLM/保存结果、
新 note ID、失败阶段与同模型恢复。临时进度或 final 标志本身不算全文质量通过。
50:37 主线程报告转写 3058.03 秒、总结 47.08 秒、总计 3106.15 秒，这是处理耗时，
不能代替原音频覆盖时长。20 秒 native 录制/暂停/继续停止另属采集验收，不计入此
四份完整录音矩阵。

## 01:17 起实际交叉测试更新

- 28:07 视频从原生桌面会议导入页选择完整下载原件并提交；任务
  `[个人标识已省略]`，目录
  `output/20261014_011709_或宇连接 & 富港北京电子 交流会议.mp4`。
  模型快照固定豆包 `asr:14:volcengine-asr:8:bigmodel` 与 Luna；attempt=1。
  01:37 实际收到 1187.8 / 1687.046 秒，speaker_analysis_ready=true；尚未 final，
  不计完整成功。新说话人 worker 单进程运行，与转写并行，完成后退出。
- 原生页面实际显示两路独立进度；步骤 2 进行中，步骤 3/4 为“待开始”。
  修复了未来保存步骤使用勾选图标的误导，只有真正完成才显示勾选。
- 官方 scrcpy 镜像接通，实际打开手机会议资料库，确认 78:10 与 22:57 两条原录音
  仍可进入详情。App Fast Refresh 原先断连，实际开发菜单 Reload 后恢复。
- 手机账号核验实机诊断：`GET /auth/v1/user` 返回 403 / `bad_jwt`；不是超时。
  当前没有尝试一次刷新旧 access token，因此本轮手机转写尚未启动。仅记录
  错误类别，不记录凭证、正文或用户标识。需修复精确错误分类与有限刷新后复验。
- 新模型适配仍存在服务端结构化时长错误透传缺口，不能保证任意新增 key 对应模型
  自动成功。客户端严格限制值校验与上传 workflow 元数据修复已准备 staging，
  当前长任务结束保存前不修改运行后端。

## 01:49 手机账号恢复与任务更新

- 修复明确 `403 bad_jwt` 的一次刷新处理；实机账号核验随后返回 200 / verifyok。
  账号页实际显示用户指定邮箱，原件未清除。此次为会话恢复，没有声称完成密码重新登录。
  三组 74 项账号回归及 TypeScript 通过；临时诊断开关已移除。
- 手机模型设置实际显示阿里云 paraformer-realtime-v2；78:10 原录音通过
  “继续处理→继续生成版本 1”启动，两路界面显示正在处理。最终转写与保存尚待验收。
  任务运行期间冻结 App 源码重载，避免中断。
- 桌面 28:07 豆包任务在 01:45:53 收到 1686.8 / 1687.046 秒后，最终识别返回失败。
  attempt=1，未换模型；此样本不能计为成功。说话人结果已保留，最终错误正在定位。

## 02:19 后端与状态修复

- 桌面会议上传的 workflow 元数据修复已应用，两种上传入口均保留会议身份。
  针对实际 router 源码新增 20 项回归通过，不改已有任务冻结记录。
- 后端安全错误分类、同模型有界重试、严格服务限制/缓存验证共 72 项通过。
  桌面仍保留同一失败任务、重试和返回入口，没有启动第二份重复任务。
- 原生桌面刷新后实际显示“提交状态”；不再将提交回执当作处理状态。
- 音频收到的时长不是最终转写完成：桌面与后端改成“已提交识别”。
  GenerateProgress 27 项、NoteGenerator 26 项分别通过；手机对应改动暂不应用，
  防止 Fast Refresh 打断实际长任务。
- 手机长任务实际两路仍运行：02:19 转写界面 257/4691 秒，独立说话人分析 47%。
  该进度不能计为最终成功。公网只读 partial 最新 session
  `[个人标识已省略]`，audioMs=286320，elapsedMs=449081。
  正在核查发送节奏/原生任务竞争与同模型重试；不凭界面低百分比推断最终失败。

- 02:28 实机仍处理：语音 612/4691 秒（13%），说话人 60%。
  录音标题中途显示“时间未知｜已恢复录音”，处理详情模型字段丢失，但两路任务仍推进。
  已列为实际失败项：需要核查元数据替换与目录恢复扫描的并发间隙，不能声称完整体验通过。
  优化和保护补丁在隔离 staging 准备，不对运行中的 App 触发 HMR。

## 02:41 实机与复审

- 手机原录音详情实际仍在推进：语音 1099/4691 秒（23%），说话人 77%。
  标题与模型详情丢失尚未修复到运行 App，不能计为验收通过。
- 桌面返回会议列表后，重新进入已有失败任务会在首次查询前短暂显示“正在生成”。
  这是恢复状态展示错误，正在修复；没有再次提交任务。
- 服务端结束协议补丁被独立复审发现提前 final 与末包写入的竞态，已退回补修。
  原先合成测试通过不代表该竞态通过，当前补丁未部署。

- 并行处理回归第一次运行 1 失败：测试仍模拟已移除的进程内 speaker 接口。
  改为隔离 worker 的当前边界后，并行、模型快照、worker 共 52 项通过。
  验证 ASR 与 speaker 同时推进、ASR 失败后保留 speaker 缓存且下次不重算，
  不替代实际长录音验收。
- 飞书回执、联系人与发布服务 99 项回归通过，未执行实际发布或发送消息。

## 02:50 恢复页与手机失败

- 原生桌面返回会议列表，再进入“导入会议文件”，实际看到“正在读取处理进度”。
  没有生成条、没有重新提交；随后恢复同一失败任务。页面回归 30 项与类型检查通过。
- 手机 78:10 在约 27% 处显示转写未完成；说话人继续至 92%，仍等待保存。
  未换模型，未启动第二份任务。此样本失败，不能计为成功。
- 公网只读核验该 session 最后 partial 为 audioMs=1310820、elapsedMs=2048631；
  对应时段没有查到 asr.failed 事件。不能把这次失败归因于服务端模型返回错误。
  手机最终保存错误及传输/账号护栏原因待核查；不输出原始识别正文或凭证。

## 02:57 手机结果确认

- 78:10 任务最终错误精确对应 App 的“转写连接中断，已完成识别保留”。
  转写 checkpoint intervals=0，没有完整区间可用，不能把 partial 当成已保存逐字稿。
  40/40 窗说话人分析已保存；generation 为 pending，原 WAV 缓存仍有引用。
- 详情重新读到原日期标题与模型；处理中出现过的临时孤儿标题仍是待修复问题。
  最终记录已备份到忽略目录 data/device-validation-20261014，原录音未修改。
- 同账号 token rotation 可能使 readSession 的 revision guard 误报切换，属于独立可达缺陷；
  本次实际错误为连接中断，未证明由该缺陷导致。
- RNFS Android read 每帧打开 InputStream 且无显式 close；读取结束后实机 fd=249。
  这一观测不能证明处理时发生 fd 耗尽。持久只读、显式关闭的 native reader 在隔离准备，
  须重新构建安装与实机复验；热更新不能交付 native 改动。

## 03:13 App 修复采用

- 原录音任务结束后采用 recording metadata 串行保护和 storage 同账号刷新保护。
  根 App 四组 27 项回归通过；实机详情仍显示原日期标题、40/40 窗分析与失败恢复入口。
- 采用独立 speaker 阶段进度事件：检测窗口、声音特征核对、最终保存分开，
  不用跨阶段 max 掩盖重置。根 App 五组 44 项回归、TypeScript 通过。
  修改后尚未运行另一份完整长任务，不能声称进度/连接全程验收通过。
- Metro、桌面、Vite、API 均保留运行；ASR 调度优化和 native reader 仍待复审/采用。
- 原生桌面插件库实际启用飞书，显示“已启用”；未新增 OAuth 权限或发送消息。
  Desktop retry 查询及账号切换保护 41 项回归通过，仍待实际发布重试验证。

## 03:33 连接与音频读取修复采用

- 独立复审后采用 App 流式识别许可保护：正常同账号核验和凭证续期不再撤销正在运行的流；退出、身份/服务地址变化及核验失败仍会撤销。最终结果保存必须核验通过。
- 已尝试发送音频后的连接中断或超时不自动重放，也不切换模型；部分返回不能冒充已保存转写。根代码六组 69 项回归及 TypeScript 检查通过。
- 已采用 Android 持久只读 PCM reader 与两个执行器的退出清理，单会话显式关闭句柄；此改动需要原生安装，不能通过 Metro 单独交付。
- 实际 Android APK 构建当前失败在 Java 的 `Unable to establish loopback connection`（UnixDomainSockets connect invalid argument），尚未完成新包安装。未停止桌面、Metro 或后端；未清除手机数据。
- 手机实际详情确认原日期标题、40/40 窗说话人分析、无已确认转写说明及继续处理入口。78 分钟识别仍是失败结果，22 分钟豆包尚未完成实际测试；不得将回归测试记为四份录音验收通过。

## 03:40 原生包安装

- 通过临时 `JAVA_TOOL_OPTIONS` 将 JDK Unix-domain 临时目录设为短的忽略目录，回环失败不再发生；未改系统防火墙或全局 Java 配置。修正 PowerShell 对带点 Gradle 参数的引用后，单 worker / 1GB 堆的 `assembleDebug` 成功（327 tasks，1m31s）。
- `adb install -r` 成功覆盖 com.vinoteapp.dev，未卸载或清除数据。Metro 8081 USB 转发仍在。桌面 Responding=True，空闲 RAM 约 3.4GB。
- 安装前手机实际返回文件库，确认 78:10、22:57 及 42 秒录音仍在会议资料分类中。安装后原生方法和完整链路仍需实际调用验证。
- App 飞书冻结导出修复已采用，六组 33 项回归及 TypeScript 通过；未外发或改权限。

## 03:46 新包短样本实测

- 安装后实际打开 VINote，默认会议页；文件库中的三份原录音保留。用已有 42 秒录音实际提交冻结阿里云模型，转写和说话人并行。
- 总处理约 71 秒，ASR request 约 57 秒；云端 session `[个人标识已省略]` 在 54846ms 返回失败，安全错误分类仅匹配 `empty`，没有 timeout/final/disconnect。说话人 checkpoint turns=0，1/1 窗分析保留。不能单凭 empty 认定服务正常或模型不可用，也不能把空窗口算说话人识别成功。
- 未生成/保存纪要，未自动切换模型；实际失败提示及手动恢复入口可见。需要区分上游明确无语音与未知空结果，不能自动伪造成功。长录音验收仍未通过。
- 源码核查发现 Aliyun finish 可在通道关闭但缺少 terminal 时结束等待，再统一给出 asr_empty_result。因而本次 empty 尚不能证明静音；部分非空文字在未取得 terminal 时也不能成为完整成功证据。正在独立准备 terminal 判定修复。
- 实测生成确认 Sheet 仍显示内部模型 ID，随后采用精确目录名称修复；根 16 项回归及 TypeScript 通过。不按 ID 猜名称，原始选择值不改变。

## 04:02 有声合成样本：真实 App 完整链路成功

- 单独创建并明确标记合成验收 WAV（38.23596 秒），非真实会议、非四份长录音验收。通过 App 会议入口和系统文件选择器导入，原选阿里云模型提交，不调整分段时长或换模型。
- 调试版原生实测日志：OPEN_OK NATIVE_SESSION，intervalBytes=1223550；CLOSE_OK EOF，reads=192，bytes=1223550，readErrors=0，remaining=0，maxReadUs=6373。只是音频读取/释放证据，不是 ASR 的独立最终确认。
- 源记录最终 state=saved，generation=null，error=false；保存 1 个完整转写区间和 1 个说话人 turn。两路并行后经 draft/audit/save，总时长86900ms；ASR request62564ms、speaker35607ms、保存191ms。
- 实机列表显示纪要已完成、标题为时间加 LLM 主题；打开版本1，正文明确这是合成验收，不是真实会议，并正确保留未安排负责人/截止时间/外发的内容。编辑、删除、导出、分享、发布到飞书和返回入口可见；这些外部交付动作尚未在此样本执行。
- 发现处理中列表行被 working 禁用，和“打开录音查看两项进度”矛盾；已交独立修复只读查看入口，重复生成/删除仍应禁止。

## 04:40 飞书重新授权与 App 版本实机检查

- 用户明确允许为既有「阳晓冰的智能助手」补齐文档转换、目录／知识库及联系人搜索并重新授权。后台用户身份新增 docx:document.block:convert，显示已开通且当前修改已发布；其他五项后台已有配置，不重复新增。
- 公网授权请求缺少转换与联系人搜索，定位 cloud.env 没有 FEISHU_SCOPES，沿用旧默认值。只添加包含原范围与上述两项的 FEISHU_SCOPES，并仅 recreate vinote-workspace workspace；未修改 ViTalk/VILab 镜像、账号权限、密钥或网络。公网 healthz、桌面 API healthz、Metro status 均 200。
- 新授权页包含两项 scope，实际确认后公网回调显示“飞书连接成功”；VINote 点击“我已完成授权”后显示“身份已核验／已连接”。
- 实际浏览知识库空间、进入软件研发子节点、返回上级成功；共享文件夹根返回无可见位置，不能据此断言目录异常或目标可写。恢复个人文档草稿选项，未保存改变发布偏好，未发送消息或增加公开分享。
- App 合成样本再次生成版本2并保存；实际从纪要操作 Sheet 打开版本与历史 Sheet，显示已保存版本2（04:15:08）与已保存版本1（04:00:41）两条。版本面板移除正文／时间去重的根修复另有4项回归及 TS 通过。未把合成样本计入四条真实录音验收。
- 文档格式转换和联系人／群交付尚待实测；四条真实录音全部成功的验收仍未完成。

## 05:13 飞书富格式实际发布与 Linux ASR 构建

- 仅切换 VINote workspace 的三文件格式转换覆盖镜像，原环境、端口、卷与实际网络名比对通过；运行镜像 ID 与候选一致，`/healthz` 返回 200。未切换 VILab 服务。
- 桌面创建独立虚构笔记「VINote｜富格式转换验收 2026-10-14」，固定正文，个人云文档位置核验通过，取消通知本人且不选择其他收件人后提交。回执为 completed，文档已创建、权限已核验、原生表格／代码块／行内样式已确认写入。
- 实际打开 私有文档链接已省略：原生表格单元格、Python 代码块、粗体／斜体／行内代码／删除线／链接及正文顺序可见。未发送消息；联系人阅读权限、群通知、图片嵌入仍未验收。
- App 实际打开纪要发布 Sheet，并展开固定发布正文预览；新重试冻结与 unknown 仅查询保护已有单 worker 43 项回归及 TS 通过，但尚未进行真实断网重试验证。
- 联合 ASR 上下文经私有加密 S3 临时传输，服务器 SHA256 与本地一致；Linux builder exit=0，镜像 ID 前缀 f8d7f00750ab。隔离 no-network／offline 三个测试 filter 串行执行中，不把构建成功算作真实 ASR 成功。
- 桌面进程 Responding=True，Vite 与 Metro 进程保持运行；未进行 Windows 重型并行构建。四份真实长录音矩阵状态仍按前表，尚未全部完成。

## 05:44 ASR 修复上线、真实双提供方探针与 App 异常发现

- 首轮 Linux lib-test 编译缺少 Docker builder 未 COPY 的测试夹具而退出 101；原日志保留。第二次仅只读挂载已校验 context 的 tests 目录，串行 offline/no-network 回归实际通过：Aliyun 21、Volcengine 42（另 1 个 live ignored）、routes 5。
- 运行镜像构建 exit=0（ID 前缀 6822fb7737d0）；原 Compose 比较中的 null 入口继承和 Docker OOM null=false 映射修正有 22 项独立合成测试，实际等价核验 exit=0。切换前两次观察到 9876 入站 established TCP/tcp6 均零；这不是全系统 authoritative idle 证明。保留原镜像与回滚 tag，仅切换 VILab 镜像，运行 ID 匹配候选。
- 公网真实 38.236 秒有声样本用原账号、指定 Aliyun 与指定 Volcengine 分别调用成功，两个结果均 144 字、covered_end=38.236、session_count=1、attempt=1、无 unrecognized。只输出计数与元数据，不输出正文、密码或 token。它们不是四条真实长录音验收，也不是原生录制测试。
- 豆包目录初为 not_available：代码审查表明持久化旧失败健康记录可覆盖配置就绪；真实成功调用后，目录两家均 available。未清空健康记录或换模型／凭据。
- 桌面从会议导入入口选择原 28:07 视频，原豆包与 LLM 选择启动 task `[个人标识已省略]`；转写与说话人并行。05:44 状态 transcribing，已提交识别 750.8/1687.046 秒，说话人区间检测约85%；完整识别尚未确认，纪要生成与保存仍待开始。忽略目录 data/dev-tasks.json 注册仅用于开发窗口显示该真实任务。
- App 的个人文档位置、无收件人发布对象核验均实际通过。真实提交发现插件未安装预检位于 unknown 冻结之后，且动态 import 引发 Metro 单独 bundle 加载；最终显示未安装插件，服务端未找到对应交付。保留原未知请求、关闭返回和 footer 精确查询已实际走过，无重复 POST 或通知。正在修复前置预检；App 正常创建文档尚未通过。
- 桌面实际点击会议导航响应正常；Windows 可用内存约2023MiB，未停 Desktop/Vite/Metro。手机两个长录音尚未重新启动，不宣称整体10分。

## 05:58 App 插件预检修正与长录音实测启动

- App 飞书预检改为静态导入并在发布 intent 进入 unknown 前执行；位置核验增加账号、epoch、请求序号和卸载保护，核验开始/失败撤销旧确认。单 worker 10 suites/83 tests 与 TypeScript 通过；已读实际修改，不将单测代替实机验收。
- App 插件库实际安装/启用已有授权的飞书内置连接，界面显示「已启用」。此操作只更新应用内启用状态，未再扩展飞书权限，未发送消息。旧 unknown 发布请求未解冻或重发。
- 手机实际从会议资料库打开原 78:10 录音，进入「继续处理」确认并提交版本1，沿用原阿里云 paraformer-realtime-v2 和原 LLM；已保存的40/40说话人分析复用。05:57 实际界面语音转写1%，说话人已完成并保存；尚未确认长音频转写/纪要成功。截图：data/device-validation-20261014/phone-78m-active-0557.png。
- 桌面豆包28:07任务继续运行，05:57已提交26:04/28:07，完整逐字稿未确认；没有重启后端或切换模型。手机启动后冻结App源码写入以免HMR影响长任务。Windows空闲内存约2196MiB，桌面仍Responding=True。

## 06:05 长录音终帧失败：未通过

- 桌面28:07豆包实际任务在05:59:46以unknown_result失败；received=1686.6、processed=0、attempt=1，未生成纪要、未自动换模型或重放。说话人结果和原文件保留。
- 公网容器安全元数据：21:59:37.968Z eof_sent sequence=-8437、flags=3、payload_bytes=1466、audio_bytes=53985466；21:59:49.969Z final_timeout eof_sent=true、final_received=false、wait_ms=12000；同session 2aaa3a25-dcee-4f25-8f6f-9cd6ec821af5随后asr.failed unknown_result。终包非空已写入，PCM量对应约1687秒；仍未取得可信final。不能仅凭客户端/服务器不同机器时间差认定提前关闭。
- 手机78:10阿里云06:03显示7%继续处理中；未改App源码或重启生产服务。实际返回箭头受working/initialFocusId禁用，安全修复方案另存 data/recordings-navigation-review-20261014；未在长任务期间触发HMR。
- 服务器旧终端输出大量partial正文后页面卡住；新建同实例只读诊断终端恢复，后续日志先在服务器过滤payload，仅输出终态类别与数字。不把partial文本当完整逐字稿或验收通过。

## 06:07 终帧调查结论与后续候选

- 核对53985466/32000=1687.0458125秒，终包量与标准化全录音一致。Desktop总deadline约2620秒，不是本次12秒终帧等待的来源。服务器EOF后final_timeout为直接失败分支；上游是否接受EOF和是否延迟final仍未知。
- 官方SAUC文档与Demo的负序号最后非空包做法一致；本次没有查得可确认的最大会话时长或long-final延迟保证，不能宣称任意模型/任意时长稳定。
- 下一诊断候选仅增加受限X-Tt-Logid与单调耗时/帧分类，隔离准备，不在手机Aliyun78分钟任务期间切换服务。桌面和手机实际状态截图：data/device-validation-20261014/desktop-and-phone-real-state-0606.png。

## 2026-10-14 06:37 Desktop retained-source adoption and actual UI

- Adopted the reviewed 19-file isolated candidate after verifying all baseline/patch hashes, apply-check, and all candidate hashes. Candidate regression: backend 136, Desktop 78, focused post-copy UI 5; TypeScript passed. These are code checks, not four-recording acceptance.
- No currently running Desktop generation was found; a retained September 15 transcribing artifact is stale evidence, not an active worker. Local source HMR/reload adopted the patch. App source/public ASR unchanged while the real 78m10s task runs.
- Actual browser FileLibrary meeting sources changed 2→3 and showed the failed 28m07s retained video. Actual native Desktop FileLibrary additionally showed a retained native 1m02s recording (4 sources). Source types/counts differ by native device records, not duplicated versions.
- Actual native file Sheet opened the failed source, played the original video, and closed back to the same meeting-purpose list. Query-only unconfirmed result and disabled original deletion were visible. Export entry was inspected, not downloaded; no generation was dispatched.
- Evidence screenshot: data/device-validation-20261014/desktop-failed-source-library-0637.png. Native Desktop responsive. App original 78m10s Aliyun task reached 39% in the actual mirrored UI; speaker evidence already saved. Final ASR/summary/save not yet passed.
- Linux diagnostics candidate archive and launcher hashes verified remotely; isolated preparation steps 01–08 passed, builder pending. No production image switch. This is observability validation, not a demonstrated long-Doubao fix.

## 2026-10-14 06:46 isolated Linux diagnostics verification

- Remote run /home/ubuntu/vinote-review-20261014-0615 completed. Complete baseline tree, exact diagnostic archive, manifest, isolated copy, apply-check/apply and candidate hashes all passed. Locked single-job builder completed.
- Offline single-CPU sequential filters: Volcengine 47 passed + 1 ignored live test; realtime metadata projection 6 passed; ASR route classification 5 passed; Aliyun 21 passed. All step and orchestrator exit codes 0. Total 79 non-live tests; no long-audio provider success implied.
- Candidate removes cumulative transcript from INFO/WARN log projection and retains bounded terminal diagnostics. No production image switch, cloud account/key/permission changes or timeout change. Next work is a controlled same-model live investigation.
- Native App 78m10s source task reached 46% submitted-audio position at 06:42; speaker evidence saved. Submitted position is not confirmed recognition coverage. No App source reload.
- Reloaded the old accumulated-output AWS terminal browser page only; local free memory improved roughly 912MiB→1927MiB. Native Desktop remains responsive. Backend/Metro/public services and the phone generation were not restarted.

## 2026-10-14 07:04 truthful recovery and remaining native gap

- Adopted only the five-file Desktop recovery UI patch after baseline/patch/candidate hashes and apply-check; isolated 42 tests and TypeScript passed. The optional frozen-context API and new-generation contract have not been adopted or implemented in the running service.
- Actual browser selection of the failed 28m source now reads “此次转写未完成，未获得可保存的完整结果”, with query-only action, original-file and history links. The contextual return restored the same purpose/query/selected file. No generation POST occurred and no old receipt was replaced.
- Actual native Desktop revealed a further issue: an unrelated meeting import receipt occupies the global intake slot and blocks querying this retained failed source. Screenshot: data/device-validation-20261014/desktop-unrelated-receipt-block-0702.png. This is not a passed recovery flow. A separate exact-task read-only route is being prepared; the unrelated receipt must remain intact.
- Actual Phone 78m10s Aliyun task reached 67% submitted-audio position / 3185 of 4691 seconds at 07:03. No confirmed final ASR yet; speaker evidence saved. Progress/navigation candidates remain isolated so HMR does not interrupt this task.
- Independent live-review harness was transferred as code only and compiled offline successfully (prepare.exit=0) using the verified diagnostic builder. No live ASR call, production image/config switch, account/permission change or old unknown replay yet. Read-only production mount discovery located the existing SQLite/config, and no retained same-length PCM was found.

## 2026-10-14 07:21 independent live test and Feishu expiry issue

- The v3 test-only harness now uses the exact public model resolver. The `14`/`8` fields in `asr:14:volcengine-asr:8:bigmodel` encode string lengths, not database row IDs. Offline compile-check and identity-check exits are 0; read-only production validation confirmed one enabled persisted provider/profile, correct kind/alias and endpoint. Private snapshot resolution exited 0. No production image, key, account or permission change.
- A fresh independent operation was started once using the verified retained 28m video converted to PCM (53985466 bytes, SHA256 `[私有摘要已省略]`). This is a new conversion; the old temporary PCM checksum was not captured, so byte-identical old input is not claimed. The adapter-only experiment uses additional terminal observation headroom without changing product timeouts. It has connected and is running, not accepted final/summary/save. Old unknown task/receipt remains unchanged.
- Actual Phone 78m Aliyun reached 87% submitted position / 4084 of 4691 seconds at 07:21, still no confirmed final. Screenshot: data/device-validation-20261014/phone-78m-pending-final-0721.png. Speaker analysis saved; no App HMR.
- Actual browser reopening a successful Feishu publication showed missing folder/wiki/contact capabilities after access-token expiry. The normal group read refreshed the token; reopening then restored capabilities and the contact search resolved 阳晓冰. This is a reproducible stale status/refresh defect, not evidence that newly approved scopes disappeared. A status-refresh fix is isolated for review.
- No mutually visible notification groups were returned. No message or recipient permission change was performed. Existing Markdown document remains successful; recipient actual reading is not verified. Deletion confirmation was opened and cancelled on the fictional format note; body remained and focus returned to Delete.

## 2026-10-14 07:29 continued review and token refresh adoption

- Root Feishu token-refresh source patch was adopted only after baseline hash and apply-check. Full seven-file regression ran on the actual root: 198 passed in 38.64 seconds (one existing deprecation warning). Public integration image is not yet updated; this does not establish that the expired-token UI defect is fixed online.
- Independent review of the 17-file exact-task/new-generation candidate found a P1: a late operation receipt response can overwrite a newer same-account read-only task and resume the wrong polling/save flow. Candidate adoption is withheld while owner/epoch/operation/route binding and request-token lock tests are added. Existing global receipt and source files are preserved.
- Actual Phone at 07:27 shows 93% / 4368 of 4691 seconds submitted, speaker result saved, final ASR still pending. No App HMR or public ASR restart. The independent 28m Doubao experiment remains one attempt with accepted_final=false; it is not a successful transcription or saved minutes.


## 2026-10-14 08:04 actual failure, adopted guards and self-notification

- Phone 78m10s Aliyun failed at 07:30 before audio.end: sentComplete=0, request=5631500ms, last submitted position 4368/4691 seconds. Original recording and 40/40 speaker analysis remain. No final transcript or summary/save success is claimed; timeout extension and account expiry are not proven causes. Evidence: data/device-validation-20261014/phone-78m-final-unconfirmed-0730.png and 78m-terminal-unconfirmed-0730.json.
- Adopted four App navigation/progress/visualization-cancellation/delete-guard patches after baselines; actual Fast Refresh hit a hook-order error, recovered using Metro full reload while no generation was active. File Library retained all four recordings. Added actual model labels using provider metadata, not opaque ID parsing; native Aliyun/Doubao rows distinguishable. App diagnostics adopted after independent review and cleanup-first-cause fix: actual root 8 suites/176 tests and TypeScript passed. This is diagnosis, not ASR success.
- Adopted 17-file exact-task/new-generation contract after independent late-receipt P1 repair and re-review. All normalized source hashes match. Actual root Desktop 85 tests and TypeScript pass. Native retained failed 28m source now opens its exact task without an unrelated intake slot blocking it; no generation POST performed. Fixed source-kind display for meeting_video/meeting_recording.
- Actual root backend initially exposed two owner preflight failures. Isolated owner-before-capture correction adopted; all normalized source hashes match and actual root 109 tests pass. This preserves 401 and owner isolation, without relaxing authentication.
- Same-model independent 28m Doubao experiment completed once with terminal_unknown/exit101. Full 53985466 bytes written and negative EOF sent. At 120001ms after EOF: 6472 binary responses, 6455 partials, final_parsed=0, parse_error=0, close=0, transport_error=0, last_flags=1, accepted_final=false. Extending final grace alone is disproven for this trial. Byte coverage is not confirmed recognition, and no partial is saved as a successful transcript. No production timeout/model/config changes.
- User specifically authorized sending one fictional test document to 阳晓冰 himself. Actual browser froze rich-format sample, personal document destination, exactly 阳晓冰 contact and no groups/self checkbox, verified destination, submitted once. UI reports completed document/native table/code/inline writing, permission verified and 本人·已发送. Existing direct collaborator role verified; recipient actual reading remains unconfirmed. No group delivery claimed.
- Feishu refresh-only image staging passed actual source hash/compile/build gates; service switch is in progress, not yet accepted. ASR service is untouched. Original media, old task results and publication receipts retained.

## 2026-10-14 08:33 actual deployment, recipient and remaining failures

- Feishu refresh-only production switch completed with the v2 launcher. The v1 unsupported Compose create flag did not replace the original container; original health/source/config were checked before correcting the launcher. New `vinote-workspace:status-refresh-20261014` is healthy; 22 configuration invariants, mounts and networks unchanged. ASR production untouched. Online full one-hour token-expiry cycle is not yet evidenced.
- Exactly one authorized fictional acceptance document was delivered to 阳晓冰: job `[个人标识已省略]`, document 私有文档链接已省略. Exact job reports completed/contact sent. Authorized Feishu session opened native body/table/code; this is not proof that the human read the notification. No group send.
- Phone 22m57s selected Doubao started at 08:05; actual UI 08:29 submitted 1062/1377 seconds (77%), 08:32 1191/1377 (86%). Speaker evidence saved; no confirmed final transcript or summary yet. Return/re-entry retained task. No App HMR/restart during this task. Screenshot `data/device-validation-20261014/phone-22m-doubao-submitted-77percent-0829.png`.
- Linux early-failure diagnostics validation v1 failed apply-check due mixed line endings; v2 passed baseline/apply/candidate/image gates but Rust compile failed E0308 at routes.rs:534 (shadowed Instant passed where Option<Instant> required). This candidate is not deployed or accepted. Isolated correction pending.
- Desktop six-file frozen model/readonly processing page patch adopted after exact LF baseline/candidate hashes. Root 74 targeted tests and TypeScript passed. Actual native UI verification in progress. No generation POST, old unknown receipt replacement or ASR model switch.
- Actual FileLibrary task originals have can_delete=false by service contract, not a temporary active-worker decision. Current disabled-delete wording suggests rechecking will enable deletion; this is misleading and under review. Originals preserved.

## 2026-10-14 08:48 matrix terminal and adopted corrections

- Phone Doubao22m57s ended unconfirmed at08:36: error code unknown_result, safe first-cause origin server_error, stage2, sentComplete=1, readerMode=1. Submitted/native-read bytes44049554 and frames6883 match; speaker12/12 preserved. This distinguishes server-reported failure after full native send from the 78m pre-EOF failure, but does not prove supplier EOS receipt. ASR request1647165ms; total1866400ms. No final transcript, summary or new saved minutes. Original and old content preserved.
- Independent pacing counterfactual failed on old code as expected; new frame budget includes read/bridge cost, reanchors after suspension and retains final/identity guards. Four App source/test files adopted only after task ended; actual root8suites177 tests and TypeScript passed. Not a demonstrated fix of missing server final. App Metro kept running.
- Readonly Desktop record copy now uses one short intro and two failure lines; source collapsed and unique parent retained. Public model metadata allowlist adopted: root55 tests passed. Actual native confirmation shows 豆包·bigmodel; historical LLM name remains unavailable rather than guessed. Confirm canceled, noPOST. Root Desktop78 targeted tests and TypeScript passed. Screenshots desktop-readonly-product-copy-0843.png / desktop-model-public-name-0845.png.
- FileLibrary inner body scrolling adopted after exactbaseline, root37 tests passed. Native actual long body scroll keeps header/close visible, task source disabled-delete copy no longer promises processing will enable deletion. Actual retained28m video rendered and played. No original deletion. Screenshot desktop-file-sheet-fixed-header-0846.png. Playback was closed with file detail; list/query preserved.
- Linux V3 safe diagnostics correction actual completed: allsteps/orchestrator0; Aliyun27,metadata9,route5,worker2=43 passed. No ASR production switch. Current ASR json-file log477435967bytes; total rotations not measured and log size alone does not establish failure root cause. Volc queue/EOF/send counters isolated candidate pending combinedLinux validation.
- Matrix remains only desktopAliyun50m37 fullPASS; desktopDoubao28m07 FAILED,phoneAliyun78m10 FAILED,phoneDoubao22m57 FAILED. No10/10or fullacceptance.

## 2026-10-14 09:02 actual entry and App copy verification

- Desktop actual Notes→粘贴链接 opens correct note intake, link tab selected, valid contextual 返回笔记 present. Supports displayed website/publicvideo/PDF/DOCX entry; this entry check did not submit/download new media or prove generation success. Source screenshot desktop-link-note-entry-0859.png.
- App presentation-only RecordingProcessingStatus patch adopted after LFbaseline/applycheck. Actual root32 progress/status tests +14 navigation/generation tests=46, TS passed. Failure outcome/next action shown once; confirmed ASR0 and speaker12/12 remain distinct; expanded detail shows only models. Native actual screenshot phone-recording-product-copy-0902.png. No retry/post/model switch from these inspections.
- Independent Volc counter review found a P2 measurement race: coverage and post-EOF counter were acquired under separate locks. v1 package was uploaded but NOT executed/deployed; v2 correction and counterfactual regression being prepared. Combined Linux ASR image has not changed.
- Reopened exact Feishu original delivery: completed/documentcreated/permissionverified/nativeblocks confirmed/contact sent and actual reading unconfirmed. No second POST/message. Group lookup is empty; asked for designated test group, no group message authorized or sent.
- Vite3100,API8900,Metro8081 continue listening; nativeVINote PID3388 responding. Windowsfree1523MiB atlastcheck. No content synchronization restored or originalfiledeleted.

## 2026-10-14 control restored and group scope

- User resumed control and explicitly waived live group sending: verify the chain only. No group message, membership or permission change performed. Desktop PID3388 responding, Vite3100/API8900/Metro8081 listening and USB reverse8081 retained.
- Volc counter v2 independently reviewed and checksum-frozen; private code upload verified and isolated Linux driver attempted. It stopped before tests/build: runtime.rs baseline expected115e5542c9acc130c60ec1be1d34824fc77857d5a42f34319503a2638eba2590, actual888295cd69e290d35b4a1747bc7b54071b84e2dc48459e4dcca1ca8dbe742a0a after AliyunV3. Bundle hashes matched. Preserve v2 failure; do not bypass baseline, overwrite evidence, or claim Linux success. Independent v3 reconciliation requested. Production ASR unchanged.
- Group-flow audit found legacy permission-cache bypass and unavailable-verification button gaps. Eight backend/Desktop/App files adopted only after exact LF baseline/apply-check/candidate hashes. Root backend95 passed; client verification pending. This is source/mock evidence, not a live group delivery/read claim. No second contact send.
- Windows available memory fell to ~595MiB; no concurrent local heavy builds started. Candidate compilation remains isolated on server. Four-recording acceptance remains1/4, long transcription unresolved.

- Group corrections root verification finished: backend95, Desktop35, App57 passed; both TypeScript checks exit0. Actual browser reopened exact original completed contact delivery and closed back to original editor; no second POST. Proof data/device-validation-20261014/feishu-original-receipt-restored-0934.png. Public group backend correction not yet deployed.
- Independent counter review resolved v2 baseline failure as raw/LF hash mismatch only:162CRLF, raw115e5542 vs normalized888295cd matches server. Preserve strict check and v2 evidence; package normalization fix/newv3 pending, no runtime code/model/timeout change.

- Counterv3 private code hashes verified, isolatedLinux strict baseline now passes. Actual sequential regression:Volc50 passed/1 live ignored,Aliyun27,logmetadata9,routes5,worker2=93 passed. Candidate image build started; not completed/deployed yet. Parent verified sourcepatch byte-identical to v2 and all dependencies_lf against normalizedactualfile bytes. Independent v3 review agent hit429; no invented approval. V2 failure retained. No live provider test or new long-ASR success from this run.

## 2026-10-14 resumed session: actual build and runtime recovery

- Restored AWS EC2 terminal read actual CounterV3 final receipt: all step exits including13-candidate-image,15-base-retained andorchestrator0. Candidate sha256:190f4edae2d24bd7208202b64bf1fcdf9d7a2ab8175a664559d1e7eaad8d818c; base sha256:6822fb7737d03e267253c64fc86055a0c13f50271c7f64b64a69b05b0a1ed271 retained. Actual93 Linux regressions passed; no live provider call or ASR production replacement from this candidate.
- Browser control then reset/lost all temporary terminals. New InstanceConnect attempts timed out; no latest private-input inventory was read. Requested user reopen existing approved terminal, without new credentials/permissions. Long same-model diagnostic has NOT started. Subagents returned429; no invented new review/patch/deployment.
- Local first session-bound launch restored desktop/API/Metro but subsequently exited. Durable hidden Start-Process node supervisors now keep canonical desktop/public andMetro8081 with logs indata/runtime-20261014. ObservedVite3100PID1740,API8900PID2288,Metro8081PID7724; desktop supervisor31748; nativeVinote launched, preserved session/task/files GET200. USBreverse8081 restored. No content/original purge, no model or timeout change, no cross-device sync enabled.
- Full acceptance remains1/4 real long recordings; three failed/unconfirmed, no new successful transcript/summary/save. Feishu group source fixes are adopted locally and tested95/35/57+twoTS but not deployed; no group send. Completed original contact receipt is preserved.

## Isolated same-model diagnostic preparation

- AWS auth restored to original orulink165328640031; InstanceConnect ubuntu shell confirmed. No permission/account changes. Old loginflow returnedbadrequest, fresh consoleflow reached authenticatedhome; no inference from unsuccessfulpasswordfieldfill. Proofdata/device-validation-20261014/aws-login-restored.png.
- Same28m Doubao frozenPCM/source inputs rechecked present. New code-only harness data/volc-counter-live-20261014 prepared; schemawhitelist rejectsrawtext/negative/strings, prepare networknone, liveonlybridge, no productionDB/env mounts/ports/retry. Restores frozenproduction finalgrace instead ofoldexperimental120sec. This is diagnostic-only; no product model/session policies changed.
- Initial multiline browserpaste stayed in input buffer; reload/readback confirmedtargetdirabsent. NativeReturn singleline codepayload submitted andverified. Initial nonrootoutputredirectfailed permissiondenied beforeprepare; corrected launcher uses existingrootpermissions insideprivate directory. New isolatedpreparestarted; no liveprovidercallyet. Old operation/receipts/frozeninputfiles untouched.

## 2026-10-14 16:39 actual diagnostic result and remaining gates

- Isolated live harness v1 Docker125 mount failure and v2 Rust101 macro recursion failure were preparation failures; neither reached the provider. V3 preparation compiled offline successfully and one new same-model Doubao28:07 diagnostic started around16:08. The frozen original and production final grace were retained; no automatic retry, model change, production replacement or saved-content mutation occurred.
- Actual v3 terminal result: exit101, terminal_unknown, source/locally-confirmed sends53985466bytes,8436 writes,0 write errors, one negative EOF8437 with1466bytes, feed1698825ms, final wait12001ms.5342 parsed binaries,5325 partial events,0 parsed final,0 parse/transport errors,0 closes. This proves complete local transmission and missing final confirmation, not successful full transcription or cloud recognition coverage. Safe numeric evidence: data/volc-counter-live-20261014-v3/actual-numeric-result.json.
- The harness directly drained events during feed without counter.dequeue. Queue peak/dequeued/delay measurements from this run are INVALID; parent corrected the earlier commentary inference that they proved backlog. Local diagnostic-only live_review.rs now accounts for this drain and rustfmt check passes; it has NOT been transferred, compiled remotely or live re-run. Original run/metadata remain unchanged. No business fix should be justified by those invalid queue counts.
- Feishu minimal candidate built successfully as sha256:3f7d981000520340dd2bc596a576bdf7fadb27f39d92a26516994ed3f0ede220. Original build wrapper ended gate failure; preserve its build.exit1. A separate exact offline verification returned Config equal, compile0, raw source95c813 exact, current baseline41d44 exact/running/healthy and wrote candidate-verification-v2.json. Cause of the first wrapper failure is still unconfirmed; local execution does not establish the earlier hypothesized escaping defect. Candidate is NOT deployed; no group send or permission change.
- Current local listeners3100/8900/8081 and native VINote responsiveness verified, USB device <device-serial> and Metro reverse8081 present; available RAM2.04GB. Actual App screen interactions were not performed in this session. Four-recording full-chain acceptance remains1/4, not10/10.
- Independent ASR architecture review confirms EOF header/negative sequence/nonempty tail agree with the official streaming protocol. Parsed-final count precedes consumer delivery, so final=0 is not evidence of a parsed final being swallowed. Current root cause remains unconfirmed. Review also found a separate full-text selection defect (nonempty utterances hide result.text); an isolated correction is being prepared and must not be claimed to fix missing final.
- Actual Desktop meeting→retained video Sheet→exact read-only task→return to same source/query→close Sheet path verified. Corrected FileLibrary progress actions distinguish meeting minutes from notes; unsupported original deletion no longer shows a deletion consequence as if available. Existing FileLibrary regression37 passed. Screenshot: data/device-validation-20261014/file-meeting-progress-copy-1647.png. These are bounded copy/navigation checks, not new ASR completion or native App UI acceptance.
- Isolated full-text selection regressions ran against actual extracted Rust functions/frame parser: baseline16 pass/6 fail, candidate22 pass. Parent adopted the exact reviewed candidate in VILab src/asr/volcengine.rs only after byte-exact baseline and candidate hash checks. Prefer nonempty aggregate result.text without changing its spacing/punctuation, otherwise existing utterance fallback. No deployment, full-crate regression or provider call; this independent defect does not resolve final=0.
- Feishu rollout helper offline109 passed. Actual read-only cloud stage blocked at saved-image identity mismatch; runtime unchanged, failed group-stage.claim/log preserved. Real Docker export is OCI: candidate3f7d is the manifest digest, distinct configblob8d9fa; index→manifest identity verified/read-only. actual-oci-chain.json contains only digest/descriptors. V2 compatibility correction is being prepared, not bypassing layer/config/source checks or deploying unverified image.
- A separate actual mock-worker reproduction proved continuous Push starvation: baseline at128 Push had0 event polls; corrected worker had7 before continuous input stopped.14 candidate mock regressions passed, including FIFO, Finish/Cancel, native errors/None, event flood and non-streaming behavior. Parent adopted exact baseline41b3→candidate6aae after hash checks. No deployed/full-crate/provider acceptance; the28m isolated harness drained per feed and does not establish this as its root cause. Unbounded output/provider queues, byte budgets, blocking provider futures and cancellation safety remain separate risks. Combined isolated Linux regression preparation is next.
- Feishu OCI V2 helper offline288 passed (179 V2 plus109 inherited). First transfer stayed buffered in a stale AWS terminal; a fresh session read confirmed V2 script/log/claim/state absent before one actual launch. Actual V2 stage passed, then switch completed: three zero idle checks, created/running22 invariants plus mounts/network equality, healthy/source verified, candidate3f7d active, no rollback. Independent read confirms ASR container still running with unchanged6822 image. Safe proof: data/feishu-group-cloud-overlay-20261014/actual-switch-v2-result.json. No group message or newly granted permissions; deployment health is not recipient reading or long-ASR acceptance.
- Before combined ASR Linux preparation, actual counterv3 worker was read-only checked:8fdb raw/LF,0CRLF, whereas reviewed current-root baseline was raw41b3/LFe54. Parent did NOT execute the known-mismatching V1 package or weaken its gate. Public source was retrieved with exact8fdb hash to data/asr-fixes-linux-20261014/actual-remote-worker.rs for narrow merge preserving deployed methods. V2 alignment/offline preparation remains outstanding. Original/media/config/credentials were not fetched or changed.
