# 实际 LLM 总结质量与进度

最近追加：2026-10-21 00:30 +08:00。历史候选使用 `codex/gpt-6-luna`，D01起按用户要求显式选择 `deepseek-v4.1-flash`。始终复用两场录屏的既有ASR、说话人与画面材料。以下是实际模型原始产物的独立评审，不是人工改写稿，也不是模型给自己的分数；各轮独立列示，不拼接最高分。

## 最近可评分的历史候选

| 形式／详略 | 样本／run | 临时分 | 操作耗时 | 产物状态 |
| --- | --- | ---: | ---: | --- |
| 文字／详细 | A-text-detailed-10 | 82/100 | 105.5秒 | raw review；守卫失败，未形成保存成品 |
| 文字／简介 | B-text-brief-03 | 90/100 | 226.7秒 | raw review；守卫失败，未形成保存成品 |
| HTML／详细 | A-html-detailed-01 | 84/100 | 108.8秒 | 已保存；原生预览和实际HTML文件导出通过 |
| 图文／精简 | B-illustrated-concise-01 | 80/100 | 106.4秒 | raw review；守卫失败，未形成保存成品 |
| 画面分镜／详细 | A-comic-detailed-01 | 77/100 | 143.0秒 | raw review；守卫失败，未形成保存成品 |
| 信息图／精简 | B-infographic-concise-02 | 81/100 | 126.2秒 | raw正文；独立计划83分，两者不能混为成品分 |

耗时来自账号绑定的operation创建至任务终态时间，不是纯provider耗时或产品预估。旧候选评审权重不同，不能横向排名、选历史最高分拼成一轮或换算成新的统一口径。每种形式仍缺同候选下另一场材料的完整成品验收。

## 统一口径的新候选

按[统一评分标准](2026-10-20-summary-quality-rubric.md)，B-infographic-concise-04 raw正文为 **72/90**，呈现10分N/A，成品总分N/A。ledger已通过，但实际流程暴露缺失状态字段；字段已修并增加真实PipelineContext测试，旧失败任务保持失败。图形计划仍有问题，不能以字段修复推断本次可成功。

A-text-detailed-13、A-html-detailed-02、B-infographic-concise-05均只有草稿，没有完整最终复核产物：读取中断、RemoteProtocolError或HTTP502，不能给最终分。它们分别耗时约256.8、140.0、141.5秒，均保留原任务和原始产物；未自动重放、换模型或追加ASR。

当前没有任何形式通过“两场×六项”的最终100分验收。结构守卫通过只表示结构与来源引用符合约束，不证明语义、覆盖或关系正确。审查继续修复真实Markdown显示、图文插入点等确定性缺陷，不在代码或提示中塞入两场会议的标准答案。

## 输入限制与服务失败

已保存的模型目录没有声明Luna图片数或上下文上限。protocol2单图能力回执仅证明单张合成图输入可用，不证明64/61张实际会议图片的上限。

A实际OCR为50846字符、64帧，B为81002字符、61帧；图片总量约13.4/10.8MiB，均未超过应用本地预算。但本地预算不等于provider能力，缺少实际token记录和明确限额拒绝，不能把连接中断或502归因于上下文超限。新增重复调用目前暂停，等待服务故障信息；不将草稿冒充最终纪要。

## 代码与桌面验证

21:33启动的448ae9b受控候选现已结束：A-text-detailed-14耗时193.835秒，ReadError且未收到headers，无draft/review，不评分；B-infographic-concise-06耗时183.338秒，完整review后因invalid_final_evidence失败，无完成稿。两次均继承原Luna和原Origin，needs_stt=false、child转写与selected parent逐字节一致，无ASR checkpoint；旧不确定任务未重放。

B06按统一口径独评为 **61/90**：事实27/35、关系13/25、覆盖13/20、可读8/10；真实呈现10分N/A，最终总分及保存成品N/A，不折算为100。受评正文SHA256为 `28b171861d7fd9822559bb6bc7fd03a8865ceaeb2751a20c1cad1939b58ae1be`，主线程按原raw4的blocks确定性拼接重新核对一致。

来源失败已定位为模型错引：首个C6删除原文重复短语，C15错窗口且quote在全文不存在；22条ASR evidence中20条通过、2条失败，未发现本次源码误拒。另有酒店价格/人数错配、赴沪航班误称返程、布展设备条件反写；图计划5个标签均不满足原文绑定，无渲染成品。本次通读131段、22个raw窗口，实看27帧，未看34帧，独评耗时8分45秒；不声称全片逐帧复核。私有报告与typed质量JSON均绑定原task和正文hash，未人工修稿或补图。

此候选没有达到目标，也不能据历史81分或结构修复宣称改善。继续批量调用不足以解决已知传输和语义问题，本轮未再提交模型任务，没有发布到知识库或发送通知。

2df3715候选的完整 `yarn verify` 530.31秒通过：后端3260项、前端1330项、桌面脚本23项，TypeScript、生产构建和文档构建通过。后续修复必须另列验证，不能追溯计入该次检查。

实际原生应用已验证两场时间档案、文件库关联定位及返回、原件文件夹定位、新版确认弹窗、HTML预览和实际HTML导出。A原视频两次实际另存为196931341字节，SHA256与原件一致。保存阶段/字节反馈补丁140项聚焦回归、独审及原生再次保存通过；补丁后TypeScript与生产构建通过。六个指定中后段位置解码通过，不声称从头到尾逐秒观看；正式安装包仍未验收。

后续正文可见性及图文插入问题已补修：360项专项、54个临时前端语法边界对照通过；另发现的脚注P2以143项聚焦回归和独立34项定向/10个host探针关闭。最后helper的冻结运行通过；最终七文件组合394项通过（15.69秒），依赖检查无冲突。它们是代码及合成材料证据，不是新模型质量分数，也不能归入此前已结束的完整verify。

PR64仍为草稿，同一功能分支继续修复；没有合并、发布、修改vilab-server或发送新的飞书通知。目标知识库的最终交付尚未完成。

## 用户要求后的服务只读诊断

已实际核对生产容器、历史用量和隧道日志，见[诊断证据](2026-10-20-luna-service-diagnosis.md)。Luna直接上游为Magpie；12:47:32Z的真实上游502、隧道EOF与Magpie容器重启集中于同一秒。另有三次约125秒的入口400与隧道context canceled，不能将所有中断都归为同一次重启或模型维护。当前health/catalog200不证明长请求已修复；本轮未再次生成，分数未增加，旧任务未重放。

## DeepSeek D01 两场真实终态与后续编码独审

以下 `.desktop-build/` 路径仅为本机忽略目录中的私有证据定位，未发布、不纳入文档站点；不上传会议原文、日志或媒体。

本段记录后续显式选择 `deepseek-v4.1-flash` 的两场 `detailed / text` 实测，冻结Origin均为 `https://api.orulink.ai`。依据已有 A质量报告：`.desktop-build/meeting-delivery-20261020/A-text-detailed-D01/quality-review.md` 与 B质量报告：`.desktop-build/meeting-delivery-20261020/B-text-detailed-D01/quality-review.md`，沿用统一 `summary-quality-20261020-v1`（事实35／关系与限定25／覆盖20／呈现10／可读性10）。D01使用原输入编码；下述WebP80仅为之后的离线候选审查，不能追溯计入这两场运行。

| 实际run / task | 终态及现存输出 | raw_review / saved_product分 | operation至终态 | 失败请求日志 |
| --- | --- | --- | --- | --- |
| A-text-detailed-D01 / `084ecd2c-45d6-473a-b108-e9b22bbb6584` | failed；无draft、完整review或最终产物 | N/A / N/A | 199.059043秒 | ReadError；headers=False；attempt=1；171.0秒 |
| B-text-detailed-D01 / `7532db9c-a43e-47b4-9e37-bcd3d2df54da` | failed；有draft，无完整review或最终产物 | N/A / N/A | 468.997179秒 | ReadError；headers=False；attempt=1；175.7秒，发生于review阶段 |

两场均为 `failed_stage=summarizing`、`summary_result_unconfirmed`、`retryable=false`；五个分项、小计和100分总分全部N/A，不给draft评分，不记0分，不归一化，不增加一组有效质量分。不存在的最终正文hash为N/A，不计算空串hash，也不用B的draft hash代替review hash。headers=False及客户端包装的502不能证明收到了真实上游HTTP502，更不能据此确定模型、输入规模或编码是根因。

运行总耗时来自本地只读receipt时间差：A为UTC 14:54:32.529384至14:57:51.588427（北京时间22:54:32.529384至22:57:51.588427）；B为UTC 14:54:30.203239至15:02:19.200418（北京时间22:54:30.203239至23:02:19.200418）。它们与表内单次失败请求耗时不同，也不使用评审等待及阅读时间充当模型耗时。运行日志分别见 A日志：`.desktop-build/meeting-delivery-20261020/A-text-detailed-D01-run.log` 和 B日志：`.desktop-build/meeting-delivery-20261020/B-text-detailed-D01-run.log`；receipt时间来源为 `.desktop-build/meeting-quality-20261019/acceptance-state/vinote.db` 的 `source_request_receipts`。

两场均默认复用原ASR、显式选择本次LLM：`asr_mode=reuse`、`llm_mode=select`、`needs_stt=false`，运行日志 **asr_requests=0**、`has_minutes=false`、`asr_checkpoint_created=false`，child无新ASR checkpoint。A选中parent `1173a77a-731e-4e23-a66a-dd8115642fb5`，B选中parent `4c0d2184-257a-471b-a0ed-9e047239f262`；各自child transcript与各自selected parent逐字节相同，原帧hash及来源绑定核验一致。这里的source identical指同一场的继承材料保持一致，不表示A/B互为同源，也不表示OCR或原ASR内容必然正确。

可复核的transcript SHA-256：A为 `61244b2da2b4338ae4043d4bbbc0864a7493c54c170f8edc7e691ad881d1724a`，B为 `4bf236a367514dcb446df23fa5d041fdde3190fb0606d3e3ada042928eef0237`；两场冻结候选清单原字节SHA-256均为 `d88dce4bff25fbefbae3d4929fbdabb490387500d652ed31a295aae45303e65b`。A完整读取27个原始ASR窗口，核验64帧hash及64项／50,846字符OCR，累计实看28张不同原图（本次20张、前序已看且hash一致8张），其余36张未视觉阅读；B完整读取22个原始窗口，核验61帧hash及61项／81,002字符OCR，实看21张、未看40张。没有将旧总结作真值，也不声称连续看完整视频。

### 后续原分辨率WebP80离线可读性抽查

独立结果见 编码可读性报告：`.desktop-build/meeting-delivery-20261020/A-text-detailed-D01/encoding-review/readability-review.md`、逐帧编码清单：`.desktop-build/meeting-delivery-20261020/A-text-detailed-D01/encoding-review/encoding-manifest.json` 和 对照区域清单：`.desktop-build/meeting-delivery-20261020/A-text-detailed-D01/encoding-review/comparison-manifest.json`。仅对私有副本调用纯编码函数；模块SHA-256为 `4ed8c67415bd1fce373132546ba09c42378892d48ae64ea06916124ddddad5ad`。保持1920×1080、RGB，WebP quality=80、method=4，候选比原JPEG至少省10%才选择，否则保留原JPEG。独立Pillow等价编码与模块的64帧最终输出逐字节一致；Pillow11.3.0／libwebp1.5.0，不承诺其他编码器版本产生相同hash。

64帧全部选择WebP，总字节14,056,766→10,542,926，减少3,513,840字节（24.9975%），单帧减少13.2437%–35.3977%；本批没有实际触发收益不足回退。另验证 `allow_webp=False` 逐帧保留原JPEG原字节。图像base64数据部分18,742,444→14,057,324字节，不含URI、JSON、提示、OCR和输出预算，不能视为完整请求大小或token计数。原图／manifest、全部时间点与顺序、OCR、transcript及source/visual refs核验未变，原产物未改。

人眼对照仅覆盖 **10个时间点、11个区域**：635、761、887（两个区域）、967、1011、1022、1125、1188、1278、1687秒。抽查价格85与67/71及对应SKU选中态、358.98/12.69小数、灰色待评估限定、ESP32P4／STM32／AS5600／minifoc节点与箭头、本人勾选和指定群未勾选。所列关键位置未见新增不可接受信息损失；967秒小灰字轻微软化但限定仍可读。1188秒原JPEG总览小字本已不足以逐字可靠阅读，文字保真记N/A，只核对拓扑，仍需保留1125/1278细节帧。其余54帧只核验字节、尺寸、时间线和hash，未做人眼编码对照。

这是有损编码的限定范围通过，不是64帧视觉全检、B场编码验收、全片通过或真实pipeline接线验收。已有DeepSeek小样本WebP probe仅证明那次格式可用，不证明64/61图或上下文上限；约25%字节节省也不证明ReadError已修复。后续使用新编码的真实run须另绑输入hash、完整raw_review与saved_product并独评，不能把本段抽查换算成D01质量分。本次文档追加没有模型、ASR、网络、飞书或任务重放操作。

## v5 原生并行生成与统一评分

A/B 均从实际 Tauri 桌面提交，使用 DeepSeek、详细文字及原有 ASR/说话人/画面材料，没有复制旧最终纪要作为输入。两次均产生完整复核响应，原未知操作未重放。

| run | 实际终态 | 操作至终态 | 统一评分 |
| --- | --- | ---: | --- |
| A-text-detailed-D02 | 成功；原生自动保存并重新打开，归入原会议档案 | 682.5秒 | **86/100**：事实34/35、关系18/25、覆盖16/20、文字呈现10/10、可读性8/10 |
| B-text-detailed-D02 | 完整 review 后来源校验失败，未形成完成稿 | 598.8秒 | **61/90**：事实26/35、关系9/25、覆盖18/20、可读性8/10；呈现10分及成品N/A，不折算100 |

A 评审对象是实际 LLM 最终正文，不是草稿或人工改稿。raw blocks、result.json.markdown 与保存记录 `d494baf2-ebc9-5c65-809e-03c7977819f2` 的 content 主线复算一致，正文SHA256为 `2dd788b05522d1d82763ea556d69f4baefcb62d7df4eef04ecbaf1ad9c49f305`，保存类型为 meeting_video。原生保存、重开和归档另有证据，内容相同不代表正式安装包或飞书交付通过。

A 确认扣分涵盖连线方向/反馈目标、报价与选中配置绑定、两项实质要求/用途遗漏、引号内表述精度与界面操作细节偏多。完整读取27个原始ASR窗口，实看28张相关帧，其中14张做原生像素核查；64张source/wire SHA核验一致。没有把字节核验当作全帧语义检查，没有用草稿、旧总结或模型自己的audit作真值。私有报告定位为 `.desktop-build/meeting-delivery-20261020/A-text-detailed-D02/quality-review.md`，不发布源正文或图片。

v5 详细文字的A/B成对分仍待定；简介、图文、HTML、画面分镜、信息图本候选尚无新的完整成对结果，不沿用历史不同口径分数填表。所有形式达到100及目标知识库最终交付尚未完成。后续三个提示文件的阶段契约修复发生在v5终态之后，不能追溯计入本次实际分数。

B 的精确守卫失败为 invalid_rejection：一个 relation 行选用仅允许 entity 的 unclear_entity 拒绝代码。29条ASR引文均唯一精确匹配，45条图像观察引用均存在，不将这次结构失败误报为引文错配。正文的图像状态和时间、价格关系仍存在独立语义错误；引用存在不代表事实正确。raw正文SHA256为 `be6da0e05531f18626a097d0a236dd2851436c651be1d7e1238da085f792228c`，完整读取22个原始窗口、实看30张原图，其余31张未逐项语义核查。私有报告为 `.desktop-build/meeting-delivery-20261020/B-text-detailed-D02/quality-review.md`。没有替模型更换拒绝代码或人工改正文，也没有据此放宽守卫。

## v6 四项并行实测与原生保存、HTML导出

本轮冻结28项运行文件，四项运行期间漂移为空；终态之后的飞书修复、提示补充和呈现修复不追溯算入该候选。仍使用DeepSeek与既有完整材料，四项无ASR checkpoint，转写与各自选定parent逐字节相同。

| run | 操作至终态 | 实际结果 | 统一评分 |
| --- | ---: | --- | --- |
| A-text-detailed-D03 | 847.1秒 | 原生提交；成功；查询原operation后自动保存 | **89/100**：事实35、关系18、覆盖18、呈现10、可读8 |
| B-text-detailed-D03 | 784.7秒 | 仅draft，复核传输结果未确认；无完成稿 | N/A，不给草稿评分 |
| A-html-detailed-V6H1 | 729.0秒 | 受控domain runner成功；原正文普通保存；原生预览与实际HTML另存为通过 | **93/100**：事实33、关系23、覆盖20、呈现10、可读7 |
| B-html-detailed-V6H1 | 790.5秒 | 完整review后精确来源校验失败；无result/note/HTML | **63/90**：事实30、关系16、覆盖9、可读8；呈现及成品N/A |

A文字note `5e12fde2-8618-55b8-aaf3-200f2c662061` 的DB正文与raw blocks、result完全一致，SHA256为 `110bc00b321b84899af3b151275a72561bdb1b584fa120c280c64b1c8336fbee`，仅一条保存记录且投影至原会议。主要扣分是驱动支路方向、候选划线状态、报价SKU限定、权限条件、多买数量与界面库存；不是数字或人名幻觉已全部修好。完整读27个ASR窗口，实看32/64张原图；全量hash核验不等于全帧语义审查。

A HTML正文SHA256为 `02544f8b44b9b8e9e1169eb66c58321f01874ecedc13b2a98121ab967301afe3`；原生SaveAs的6775字节HTML文件SHA256为 `cdafe545e6f9f0051d55f1814c9f09d53e3a28de7908e27ee737c961bab938e3`。导出字节与renderer对原正文的输出相同；可见文本、全部章节、安全CSP和离线窄屏检查通过。该稿仍存在图示端点泛化、OCR误读变成编号冲突、坏ASR措辞和过程库存。完整读27个窗口、实看22/64张图。domain runner及程序保存不冒充原生生成提交；原生预览/导出另有实际证据。

B HTML的C15引用把原ASR逗号变成问号，32条ASR引用中31条精确匹配、1条失败；不修改原响应或放宽守卫。正文SHA256为 `c0695e6edd76257d5b0057cec1b1c2d2fa99b1f4f7964d3f1df66ad586eceeab`。空checkbox、出发节点和900/600口径已改善；现价/划线价、同趟事件拆分、组合规格、设备支持渠道、展位差异及协作后续仍有错误或遗漏。完整读22个窗口、实看18/61张图。本项不渲染失败正文来补呈现分。

旧A D02勘误：复看清晰原图，“这个是对齐过了”确有来源，原F1扣1撤回，86分更正为87分。旧原报告不改，明确另记本勘误；这不是模型优化所得1分，不与v6成果混算。

当前文字与HTML均缺两场完整成对通过，其余形式本轮尚无成对成品。全部100分、目标知识库实际交付、正式包验收仍未完成。PR64保持草稿，未合并、部署或追加飞书通知。
