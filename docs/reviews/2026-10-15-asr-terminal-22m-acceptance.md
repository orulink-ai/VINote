# 22分57秒录音跨客户端、跨 ASR 验收

日期：2026-10-15。此表独立记录本轮，不覆盖此前四份录音的失败或未知结果。

## 验收范围

同一份保留的 1376.548571 秒录音，分别验证桌面/App × 豆包/阿里云。必须经过真实客户端提交、转写、并行说话人分析、纪要生成、保存及重新打开，才能标记通过。未知结果不自动重放，失败不切换模型；原文件、历史任务及凭证不清理。跨设备同步、纪要图片可视化保持取消。

| 客户端 | ASR | 实际结果 |
| --- | --- | --- |
| 桌面 Tauri | 阿里云 paraformer-realtime-v2 | 已完成并实际保存、从会议列表重新打开 |
| 桌面 Tauri | 豆包 | 新部署后失败：提供方中途返回 55000000，未取得完整转写；未通过 |
| Android App | 阿里云 paraformer-realtime-v2 | 实际错误为 socket_error / unknown_result；已暂停、保留说话人结果，未通过 |
| Android App | 豆包 | 待修复部署后实测 |

## 桌面阿里云实机证据

- 通过原生客户端导入保留的 `source_audio.m4a`（22,266,052 字节），明确选择阿里云和 gpt-6-luna；没有修改旧未知任务。
- 任务：`[个人标识已省略]`，任务目录 `output/20261015_154449_source_audio.m4a`。
- 首次 ASR 在完整发送前出现 `asr_stream_failed`；现有有界重试使用同一模型，第二次成功。不能隐去此次瞬时失败或声称首次成功。
- 成功时间：16:10:48 +08。processed_seconds=1376.548571，received_seconds=1376.5485625；成功尝试 session_count=1。完整会话文本 6422 字；说话人对齐后 414 段。整会话文本的后续时间对齐不能声称为提供方精确词级时间戳。
- 说话人分析与转写并行，完成后进入纪要生成。
- 已保存内容 ID：`[个人标识已省略]`。
- 标题：`2026-10-15 15:44｜展会参展安排与现场物料准备`。实际点击返回会议、从列表打开，正文可读。
- 实机截图：`data/device-validation-20261015/desktop-aliyun-22m-saved.png`。截图及原文件不提交。

## 服务端修复与部署边界

- VILab 功能分支 `codex/asr-terminal-coverage-fairness`，提交 `2636dd740ed8fd32b4ad9304100969b9c2cc390b`：`fix(asr): wait for provider progress and preserve terminal coverage`。
- 豆包结束等待区分有效提供方进度的空闲期限与独立总期限，不以本地音频发送速度假定提供方已识别完成。总期限默认依据原录音 PCM 时长及等待宽限计算，不写死录音分段时长，不替换模型。只有符合协议的终态才能成功；进度数值不等于终态回执。
- 保留完整文本优先规则、worker 公平调度与单次 EOF 行为。此修复不等于已证明此前 final=0 的唯一根因。
- 提交源码在独立 Linux 环境的实际回归：豆包49通过/1个需在线调用的测试跳过；阿里云17、日志6、路由5、worker12通过，共89通过。均为离线测试，不是提供方或实机验收。
- release 构建在服务器独立目录以1 CPU、3 GiB上限执行。尚未因该构建替换生产 ASR 镜像。
- 部署审查发现需要保留线上已有的安全日志/数值诊断；补齐并复验后才能部署，不能以89项通过跳过此项。
- 安全诊断已从实际服务的已验证基线逐字恢复并提交 `989b477f687e0211089ce2869421349d87c2fb40`（`fix(asr): retain safe provider and route diagnostics`），worker 公平调度及其12项回归保留。该提交实际 Linux 五组回归分别49/25/9/5/12，共100通过、1个在线测试跳过；增量 release 构建仍需读取最终成功回执。
- 独立审查又发现 final 验证到缓存发布、idle 进度复核到超时决定的两个并发窗口，正在修复。未部署 `989b477`，不能把离线通过视为这两个窗口已消除。
- 服务没有统一全局活动任务 registry。观察到容器网络命名空间没有 established TCP 连接，只能说明观察时未见连接，不能据此伪造 `active_asr=0` / `active_other_jobs=0`。维护部署须记录此限制、实际观察与保留回滚，不声称绝对全局空闲。
- 两处并发窗口修复已提交 `19fc9cecf52bac6c2fb798c2415a4af31d1df5a6`（`fix(asr): make final and idle timeout decisions atomic`）。最终纯提交包已通过服务器五组实际 Linux 回归51/25/9/5/12，共102通过、1个在线测试跳过；release 构建尚未确认完成。新增两项回归通过屏障控制并发顺序，不使用真实 provider 或真实长录音冒充离线测试。
- 上述三个提交已推送远端 `origin/codex/asr-terminal-coverage-fairness`；没有创建 PR 或合并默认分支。
- 最终 Linux release 和 orchestrator 均实际 exit0，构建身份、两个二进制哈希和102项计数已保存 `data/asr-release-20261015/actual-final-build-19fc9ce.json`。这仍不是模型在线验收。
- 第一次候选镜像准备在 `compose_config_drift` 停止，生产容器未修改。只读对账确认当前 Compose 与运行镜像相同，环境变量（合并镜像默认值后）、命令、默认入口、端口、卷、网络与重启策略一致；运行容器的资源限制为默认值。历史 Compose hash 不作为语义相等证明，部署助手改为八字段严格有效值比较，未知字段/真实差异/外部限额继续拒绝；实际创建后的全 Config/HostConfig、挂载和网络投影及回滚门禁保留。更新助手10项离线回归通过，V2镜像准备待结果。
- V2实际镜像准备成功。三次新的观察均无 established TCP 后已完成本次授权维护，`deploy.exit=0`、`PASS single-service switch`，镜像 `sha256:1ea26e9dc0de65a3acdbb13f482db0d785a9fa6eb56f3aacf6e01684bb4b4764`。实际创建后所有投影相等，无回滚；独立再次读取 health 为 `19fc9cecf52bac6c2fb798c2415a4af31d1df5a6`、dirty=false。完整安全回执位于 `data/asr-release-20261015/actual-final-deployment-19fc9ce.json`。
- 新部署后桌面真实点击生成：任务 `[个人标识已省略]`、目录 `output/20261015_165504_source_audio.m4a`，冻结模型豆包 `asr:14:volcengine-asr:8:bigmodel` 与 `codex/gpt-6-luna`。手机真实点击“生成版本1”，来源标题 `2026-10-15 16:14｜VINote-22m57s-ASR-test`，确认页明确阿里云。两条提交均为新操作，旧未知任务未重放；进行中不计通过。
- 实际只读检查目标运行容器的网络命名空间，连续三次 established=0；只读 WAL-aware SQLite 查询中 `note_runs` 和 `runtime_install_jobs` 的状态聚合均为空。部署助手另采集最新三次带容器/PID/namespace 绑定的观察，记录未知全局计数与维护限制，仍要求单服务 image override、全部配置不变和失败回滚。

## 待处理的可见问题

- 会议编辑器加载态仍有“正在读取笔记”文案，需按真实内容种类区分；此项尚未修改。
- 其余三项真实22分57秒测试未完成，不能将整体验收标记满分。

## 17:19 后停止消耗额度：仅离线排查

- 用户明确要求修复确认前不再调用云端。停止新 ASR/LLM 提交、长录音重跑和自动重试；只读既有任务与服务器日志，离线复现和回归。不得用重复在线尝试代替定位。
- 桌面豆包任务 `[个人标识已省略]` 已失败，服务回报收到音频 745.6 / 1376.549 秒，说话人证据已保存，未产生最终逐字稿或纪要。
- 实际服务器既有日志确认会话 `[个人标识已省略]` 收到 `provider_error`，`provider_code=55000000`、flags=0、compression=0；结束摘要 elapsed_ms=780905、source_bytes=23955200、outcome=cancel。此错误发生在完整音频提交之前，不是此次 EOF 等待超时；不能把此前 EOF 并发窗口修复称为此次失败根因的修复。
- 对应上游排障标识 `202610151655148AF5B59C5168022C4020`，仅供定向排查；日志不保存音频、识别正文或凭证。
- 手机阿里云处理中曾显示服务回报约220秒、最终确认区间为0。同时间存在上游 `40000004` 日志，终态距离最后写入约10195毫秒，但没有客户端 session 绑定，不能确认为这份手机任务的根因。设备电源证据显示此次运行保持唤醒。
- App 源码的 `asr_stream_failed` 属于明确 ASRServiceFailure，不会自动重试；并行说话人完成后会抛出 ASR 失败并跳过 LLM。说话人本身可继续保存 checkpoint。实际安装 APK 包含原生 PCM reader，当前 VINotePCM 日志未能证明此次 reader 路径和停止点。
- 已确认失败展示存在潜在等待点：ASR promise 要等待 reader.close 才拒绝，最终错误落盘又等待说话人分支；正在离线验证，不把此展示问题当作云端断流根因。
- 本机只读检查 3100、8900、8081 仍监听；未重启或关闭两端热更新。
- 17:27 读取手机此份实际录音元数据：generation.status=paused，errorCode=unknown_result，origin=socket_error，readerMode=1；submittedBytes/nativeReadBytes均38105600，submittedFrames/nativeReadCount均5954，sentComplete=0。证明本次确实使用原生 reader、桥接提交约1190.8秒，不是已证明卡在220秒读包。最终转写区间0，说话人checkpoint v1保留519个区间，无纪要保存。后续不得把同时间其他会话的idle错误直接归到此录音。
- 快速离线回归：转写传输/重试72通过；App生成/防重放/状态54通过；后端并行分析/完整产物保存/安全失败落盘34通过。视频纪要旧测试仍要求已取消的视觉模型调用与截图，按当前取消合同修正为不调用视觉模型、不生成截图、保留原视频；没有恢复额外模型调用。
- 已实际修正 App 明确失败的通知时序：`recognizeInterval` 启动清理后立即以可选回调通知，原 Promise 仍等待 reader.close，生成锁不提前释放；限额续接、取消、身份失效不写失败通知，观察回调异常不阻断清理。`meetingCloud` 仅转发静态失败进度，不增加任何 ASR/LLM 调用。不宣称这项修正解决了 socket_error 或豆包55000000。
- 最新 App 四组离线回归 `asrStream / generateRecording / asrReplaySafety / recordingProcessingStatus` 共79通过；typecheck通过。后端34项通过。服务端功能分支保持现有已推送19fc9ce，本轮没有再次部署或在线重跑。最终两端实际长录音验收仍不通过。
- 完整长度零额度传输回归新增1项通过：真实 `recognizeInterval`、fakeTimers、模拟WS回执，精确发送44,049,554 PCM字节/6883帧，末帧4754字节；单socket、冻结模型、单LAST，全量检查序号/长度，发送完成及partial均不能冒充final。测试2.512秒、进程4.474秒，计数socket丢弃payload。该测试只证明客户端完整长度协议路径，不证明上游真实长录音已成功。
- 独立只读审查失败通知接线通过：未提前释放锁，通知前检查原身份scope，cleanup先挂接且回调异常隔离。本轮没有新云端音频或LLM提交；手机任务已实际paused，保留519个说话人区间和原录音。

## 后续根因排查（继续禁止修复前云调用）

- 再读既有服务日志：豆包失败时 route 的 idleMs=76，748600ms/3743帧/23955200字节已接收；provider writer confirmed_bytes=23948800，仅少为LAST保留的一包6400字节。不能把此次失败归为桌面/VILab大规模上行停顿。最后provider ErrorMessage的code=55000000，terminal_phase=open、submitted=false；没有进入EOF。
- provider摘要 binary=3652、partial=3615、ping=52、close=0、transport_error=0、final=0；parse_error=1包含最后的provider错误帧，不证明JSON解析错误。provider duration=730000ms、utterance end=728152ms、definite end=715032ms。位置差不能直接称模型处理积压。
- invalid_positions=722 是反复检查全量返回字段的累计次数；不代表722包损坏或722段丢失。该诊断仅影响位置观察与EOF后等待，本次在EOF之前失败，不作为已确认因果。
- 实际公网经Cloudflare进入Nginx的api-hk站点，WebSocket Upgrade/Connection头已配置，buffering=off，read_timeout=300s。故障窗口现存Nginx error.log没有筛到对应ASR错误；不是彻底排除代理问题的证明，未更改代理或凭据。
- App真实RN实现存在确定缺陷：WebSocket.send只入native桥，native忽略OkHttp send=false；首个无详情error事件覆盖之后close携带的异常消息。38105600字节仅为桥接提交，不能声称已上网。OkHttp本地字节码有16MiB发送队列上限，但未取得本次队列高水位，不能断言本次溢出。
- 开始实现专属Android ASR原生传输确认与有界背压，保持VLA2协议、选定模型、单次LAST及独立cleanup锁。未全局patch RN，未开启自动重试。主审已指出必须用真实JS fixture验证小端帧，以及异步LAST ACK与final重排、native销毁后迟到回调等边界，修复完成前不安装/不云测。

## 18:22 后复核：继续处理应用与服务调用实现

- 用户要求回到 VINote/VILab 实现排查，已停止火山控制台登录方向；没有向该站提交凭据或重新上传音频。
- 服务端确定的传输/资源回收修复提交为 `6adcac3429986621b9523a22a24b04220c57d556`，分支仍为 `codex/asr-terminal-coverage-fairness`。新增有界可靠消息队列、可替换完整 partial、终态发送期限；EOF 等待继续读取控制帧，客户端断开会取消实际 ASR worker。它们是已验证的软件缺陷修复，不能被描述成已证明消除了中途550错误。
- 本机实际服务回归110通过、1在线测试跳过；独立服务器无网络 Linux 构建进程1849266已确认启动，源码包和传输哈希校验成功。尚未确认本轮 Linux 结果、未部署新提交、未新调用提供方。
- Android专属OkHttp传输已通过8项真实本机WebSocket场景，包括正常收尾、慢读、send=false、突然断开、取消/迟到消息、拒绝重定向，以及观察回调抛错后释放与重新建立会话。bridge `peerClosing.code` 与实际JS adapter契约也已校验；最新相关JS48项及类型检查通过。上述本机服务器并非真实ASR提供方。
- 新App APK尚未构建完成：Gradle在项目编译前的JDK17 loopback初始化异常受阻；继续定位，不卸载、不清数据、不宣称手机已更新或长录音通过。
- 只读复核未发现足以确定550根因的PCM格式、首包、序号或EOF错误；VILab出口没有独立发送节奏控制，接收积压时可能出现突发，正在以本机适配器实验核对，尚未盲改节奏或切换模型。
- 3100/8900/8081监听进程仍分别为29336/544/24876，两端开发服务保留。
- 第一次Linux构建未进入编译：执行身份ubuntu无权读取既有root构建基线，未修改任何原目录权限。使用现有sudo在独立新目录 `vinote-review-20261015-transport-6adcac3-root` 启动进程1868001后，六组真实Linux回归已全部通过（豆包52、阿里云25、日志9、路由5、worker12、outbound7，共110，在线用例1项跳过）；release二进制仍待完成。新提交6adcac3已推送同名远端功能分支，无默认分支合并、无新部署。

## 18:38 后 App 构建与保留数据更新

- Gradle阻塞已解决：JDK的Unix-domain pipe临时路径在本机连接时报Invalid argument；仅构建进程设置 `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=D:/projects/VINote/data/jdk-pipe`，未修改系统设置。单worker、512MiB堆、256MiB metaspace，Gradle实际2分12秒exit0。
- ARM64 debug APK SHA256 `[私有摘要已省略]`，签名检查通过、包含专属ASR模块。实际 `adb install -r` 返回Success，手机包lastUpdateTime=2026-10-15 18:38:57；未卸载、未清除数据。
- 已实际打开新版App，Metro重新bundle成功，会议首页与文件库可见；文件库仍保留78分10秒和22分57秒原录音。打开旧失败录音显示“转写结果尚未确认”、明确不自动重发、保留12/12说话人分析，点击返回后文件库恢复；元数据仍为paused、519个说话人区间、0个已确认转写区间。未点击重试或发起新生成。
- 实机截图 `data/device-validation-20261015/app-updated-original-preserved.jpg`；包与构建日志/回执保存在App开发记录中。页面运行并不证明新增原生传输已经完成真实提供方验收。
- 服务端6adcac3的独立Linux release实际2分27秒构建成功，release-build.exit与orchestrator.exit均0；两个二进制及build-result回执已产生，仍未部署。
- 真实本机WS适配器积压实验：正常输入的中位包间隔202ms，集中输入16包时15帧/3秒PCM在0.302ms内到达peer；两组字节完全一致、顺序一致、仅一个EOF。证明出口会快速排空积压，不证明历史550错误由此触发。正在按协议审查最小防突发修复，尚未新增云调用。

## 后续有界等待与出口节奏复验

- 新版App实际Hermes DEV运行时已执行synthetic拒绝探针：protocolVersion=1、connect/enqueue/close存在，非法Origin/非整数PCM/超长binary和text分别拒绝为ASR_TRANSPORT_10，无会话enqueue为ASR_TRANSPORT_1，cleanup=true。探针不使用真实token、录音或提供方URL；回执 `data/device-validation-20261015/app-native-rejection-probe.json`。这证明真实安装的原生模块可用，不证明云端成功传输。
- 两端旧 `1.5D+90` 整个会话期限在约D秒实时上传后仅余 `0.5D+90`，小于当前豆包默认 `D+12` 收尾预算。已分为上传和确认LAST之后的独立有界收尾期限，partial不能续期、未确认或过期后的LAST不能复活操作。App相关72项离线回归与typecheck通过；Python相关97项通过，含真实sender线程/实际transcriber调用的断网不重放验证。未新增服务端预算协商，不声称覆盖管理员任意超长override。
- 桌面binary发送前记录audio_attempted；之后断开、发送失败或期限耗尽为unknown_result，不自动重传。明确服务错误保留原code，但不再授权静默重传音频；发送前连接故障的有限重试及服务明确的会话续接保留。详见 `docs/asr-stream-timeouts.md`。
- VILab提交 `91ee4b23e2235fe7cd3db242ff97e8b3794e4cde` 按每包真实PCM字节数/采样率约束出口，包含EOF尾包，延迟后不积累追赶额度；native worker逐命令poll事件，保留取消与FIFO。无独立录音分段、模型切换或音频重发。
- 91ee独立Linux复验真实失败：53通过、3失败、1在线用例跳过，停止部署。失败为peer接收间隔断言（61.53ms/162.89ms及暂停间隔），不能以其直接证明writer违背自己的时间线，也不能隐去失败。本地保留 `data/asr-release-20261015/linux-91ee4b2-pacing-failure.txt`。
- 已提交 `823226b09639f722ebc7ab1351ddf5710c874875`，通过cfg(test)窄observer核对生产writer真实完成时刻和下一包期限；TCP peer继续检查字节/顺序/EOF，worker保留partial与取消检查，没有放宽原发送期限或修改模型。相关本机114通过、1在线用例跳过；新的纯提交包18文件、哈希已冻结，独立Linux复验待结果。
- 此时公网health仍为19fc9ce、dirty=false；未部署91ee或823226b，未新增ASR/LLM调用，真实验收矩阵仍维持前文结果。

## 修复部署后的受控实机复验（尚未全项通过）

- 823226b独立Linux六组实际114通过、0失败、1在线测试跳过，release-build与orchestrator均exit0。候选镜像 `sha256:844a171472708ba559653de326f12081ecf18e5f12c9c063e8cfb62328116b3b` 已实际单服务切换，deploy.exit=0、invariant_hashes_match=true；公网health独立确认823226b、dirty=false。配置/账号权限未随镜像更改，保留旧镜像1ea26e9d回滚。新鲜三次连接观察由门禁验证，全局活动作业数仍未知。回执 `data/asr-release-20261015/actual-deployment-823226b.json`；分支已推送远端。
- 首轮受控新请求：桌面豆包任务 `[个人标识已省略]`，19:20实际确认独立新操作，沿用冻结的豆包bigmodel和gpt-6-luna，1376.549秒原件。19:25:07本机记录asr_provider_error；服务会话 `[个人标识已省略]` 于11:25:08Z明确收到55000000、flags0、compression0。attempt1即停止，retryable=false，未自动重传、未切换模型、未进入LLM或保存纪要。
- 本次豆包provider摘要：upstream_log_id `202610151920298E870B11CE258CBBED77`，endpoint_mode=bidirectional，elapsed_ms=279308、source_bytes=8499200、confirmed_bytes=8492800，terminal_phase=open、submitted=false，仍未到EOF。UI最后回报262.6/1376.549秒。**本次仍失败，不能把出口节奏/收尾修复说成已解决550根因。** 实机截图 `data/device-validation-20261015/desktop-doubao-823226b-failed.jpg`。
- 实际只读白名单配置确认PCM s16le/16kHz/mono、bigmodel原生流式、标准双向endpoint、duration资源，ITN/punc/utterances均true、finish idle12000ms、total override为空；不含任何密钥。证据 `data/device-validation-20261015/deployed-volc-config-823226b.json`，这是落盘配置核对，不冒充故障时内存快照。通用错误正文此前未保留；没有依据该码判定额度、格式或某个固定时长上限。
- App本轮保留原阿里云选择，19:22:55.839820 +08:00（服务日志为11:22:55.839820Z）开始同份约1377秒录音，唯一会话 `[个人标识已省略]`。通过实际native既有partial只读观测绑定，未新建ASR连接；证据 `data/device-validation-20261015/app-aliyun-active-session.json`。持久化generation.startedAt仍为旧值，不能当成本轮开始时间。
- App实际处理中返回文件库，顶栏继续显示进度，经任务恢复页进入同一录音后继续增长；未重新提交。19:45已到1182/1377秒85%，已保存转写区间仍0，等待完整final。仍未计通过，所有后续新豆包调用已暂停。
- ViTalk实际本机配置及已有trace连接LAN `192.168.1.143:9876`，相同模型ID；现有成功样本仅3–17秒。LAN/public免费health的boot serviceId不同，LAN无build字段、公网823226b；未证明同一服务配置，未访问LAN凭据或更改LAN部署。不能用这些短样本给本次公网长录音背书。

## App 完整转写回执与纪要阶段阻塞

- App 阿里云会话 `[个人标识已省略]` 的已有服务器日志实际返回 `asr.final`（2026-10-15T11:48:35.795335Z，finalTextChars=6445）及 `session.completed`（11:48:35.795448Z，totalMs=1541079）。没有为查询回执再次发送音频或调用模型。
- 手机实际元数据保留版本5转写区间0–1376.5485625秒、6445字识别正文，带区间标记的transcript共6469字；说话人519区间仍在。证明这一轮整段ASR成功，不等于纪要已生成保存。
- 后续事实提取阶段保存1个summary checkpoint；第二部分收到首字后以含“账号”的错误暂停，generation.status=paused、noteId为空。正在定位账号/请求生命周期问题，尚未确认根因；不会删除转写checkpoint或重新提交整段ASR来恢复纪要。
- 精确只读错误为 `账号或服务已切换，原操作已停止；本机稿仍保留`（SessionScopeChangedError 文案），不是ASR提供方错误；实际设备暂停截图 `data/device-validation-20261015/app-aliyun-full-transcript-summary-paused.jpg`。正在离线验证并行纪要请求的凭证刷新竞态；没有据文案断言用户真的切换过账号。
- App同身份不同请求context并发刷新凭证的离线回归先失败（预期1次、实际2次），修复为独立生命周期下串行刷新并复用前一轮新凭证；保持真实账号切换、A→B→A、取消与MCP/飞书scope限制。相关5套105项通过、2条摘要恢复定向测试及typecheck通过；日志为已有工具输出摘录，不冒充完整原始日志。旧摘要测试仍有v9断言与当前v10不符，未为过测降版本。证据 `data/runtime-20261015/app-refresh-before-failure-excerpt.log`、`app-refresh-105-tests-passed.log`。
- 20:01后实际点击原录音“重试生成纪要”→“重试生成版本1”；继续冻结的阿里云与gpt-6-luna，保留完整转写和已保存 `facts:1`（并行提取中先完成的是第二部分）。恢复正重新校验原件并重建临时PCM，尚未计纪要保存成功；没有删除原录音或清空checkpoint。
- 20:04实际恢复成功：generation清除、error清除，note_id=`app-1792052063450-tqgk6b9acq`，保留4份facts及draft/audit。恢复timings没有asr-request阶段（音频缓存准备124825ms、转写缓存校验125955ms、note-save179ms、恢复全程161804ms），完整区间和519个说话人区间保留；未切换模型。用户确认的恢复仅调用缺少的事实提取、初稿与核查，未重转写。
- 已实际操作保存版本1→打开纪要正文→返回原录音→返回任务与恢复→返回文件库→会议主列表→重新打开同一纪要，返回入口分别对应真实来源；会议列表独立显示该纪要。未发送飞书消息，未点击版本2提交。结束时误触的版本2准备面板已关闭，无新generation。实机证据 `data/device-validation-20261015/app-aliyun-22m-saved.jpg`、内容无关元数据回执 `app-aliyun-22m-final-receipt.json`。
- 此项仅通过App阿里云22分57秒的转写、独立说话人结果保存、纪要生成/核查/保存/重新打开与返回链路；不证明说话人身份准确率或全应用验收。桌面阿里云既有同长录音成功证据在前文；桌面豆包当前仍55000000失败，App豆包没有为凑矩阵发起新的收费调用。
- 豆包安全错误首因诊断新增提交 `838a471` 已推送 `codex/asr-terminal-coverage-fairness`：仅保留固定枚举/数字/形状，不保存错误正文、密钥或哈希；首因不被后续drop覆盖，未知保留unclassified。离线93通过、1在线用例跳过；尚未部署，不声称该诊断修改已解决550根因。
