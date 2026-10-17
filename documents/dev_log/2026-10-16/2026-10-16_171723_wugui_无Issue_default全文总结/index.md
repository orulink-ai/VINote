# default 全文总结与整体事实核对

- 2026-10-16 Asia/Shanghai；作者 wugui，参与 Codex；无 Issue；本地实施与离线验证完成，未提交/部署。
- 用户明确取消default按固定chars/segments自动分层：全文one-shot+既有整体事实核对。保留显式legacy accurate分段兼容，无UI；不按模型名判断能力、不切模型/重试、不写死context上限。
- 写集只限openai_llm.py与相关tests/docs/AGENTS；不改cloudservice、UI、ASR、真实任务产物，不执行云推理。
- 现状：summarize对default调用_should_use_hierarchical_mode，按SUMMARY_DEFAULT_MAX_*触发；已有test_summary_modes明确断言长输入分层，需要更新为新合同。会议one-shot已有全原文review，无需另造事实核对路径。
- 验收：字符/段数/evidence超过旧阈值仍一次全量draft+一次整体review；显式accurate不变；服务context拒绝原样失败不降级/不重试；真实transcript pipeline离线证明ASR/speaker不调用、原文保留。

## 验证

- Red：先调整旧default自动分层测试并加精准用例，实际6 failed/6 passed，default仍走chunk路径，匹配目标缺陷。
- 实现：openai_llm.py删除_should_use_hierarchical_mode，仅显式accurate分层；default/oneshot统一既有全文one-shot+会议整体review。无context上限或模型分支、无新增catch/retry/fallback，既有服务错误原样传播。
- Green：7模块首轮64 passed。再加真实transcript pipeline在draft/review拒绝时仍保全文两例，最终 **66 passed，1.48秒**；新增测试11例，另更新1个旧合同断言。目标tracked diff whitespace检查无错误。
- [正式合同与完整命令](../../../../docs/reviews/2026-10-16-default-full-summary.md)。AGENTS已更新Runtime Flow、默认策略及legacy配置说明。
- backend写集仅openai_llm.py；未改cloudservice/prompts/UI/ASR/模型设置/真实task文件。策略代码结束后已通知父端冻结源码，此后仅tests/docs收尾。未运行云端、重启进程、调用真实任务get_status或操作手机。
