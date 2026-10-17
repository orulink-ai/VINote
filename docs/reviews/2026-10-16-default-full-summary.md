# default 全文总结合同与离线验证

2026-10-16，仅本地源码/离线证据；不代表云模型结果验收。

## 当前行为

`_BasePromptLLM.summarize` 对 `default` 与显式 `oneshot` 都调用全文 `_summarize_one_shot`。完整 transcript segments、speaker evidence、extras 一起生成草稿；会议再沿既有整体事实核对路径，提供完整原资料和草稿，返回核对后的正文。通常是一次全文 draft + 一次整体 review，不是把资料拆成多段，也不取消事实核对。

删除按 `SUMMARY_DEFAULT_MAX_CHARS/SEGMENTS` 自动升级策略的私有判断。这两个配置字段暂留兼容，但不再决定 default 分段。只有显式 legacy `accurate` 继续使用原 chunk/review/merge 路径及 `SUMMARY_CHUNK_*`；不新增UI策略选择。

不按模型名判断context、不写死任何厂商/模型上限；不截断原文、不自动分段降级、不换模型、不自动重放。全文 draft 或 review 被所选服务拒绝时，保留原服务异常与已保存 transcript，由既有任务错误路径报告失败。本改动不为未知400伪造“必然超context”的判断，也不改 cloudservice 的安全错误投影或既有review配置。

## 写集

- `app/llm/openai_llm.py`：仅策略分派，移除default固定阈值判断。
- `tests/test_summary_modes.py`：旧“长default自动分层”断言改为全文单次draft；显式accurate兼容断言保留。
- `tests/test_default_full_summary.py`：新增11个参数化执行用例，覆盖旧字符/段数/evidence阈值、default/oneshot全文与整体review、draft/review context拒绝不降级不重试、真实transcript pipeline正常及失败时保留全文且不调用ASR/speaker。
- `AGENTS.md` 与本证据/开发档案。未修改prompts、cloudservice、UI、模型设置或真实任务产物。

## 证据

先改测试：**6 failed / 6 passed**，default仍尝试分段，失败与本次目标对应。实现后首轮64 passed；补pipeline异常保全文两例后，最终：

```
.venv/Scripts/python.exe -m pytest tests/test_summary_modes.py tests/test_default_full_summary.py tests/test_meeting_review.py tests/test_anthropic_llm.py tests/test_note_service.py tests/test_cloud_chat_failure_classification.py tests/test_cloud_chat_stream.py -q --tb=short
```

**66 passed，1.48秒**。目标tracked diff whitespace检查无错误。全部调用为离线记录器/stub；transcript integration走真实NoteService/prompt/review/保存流程，ASR与speaker入口设置为一旦调用就失败。异常时transcript仍完整，既无result也不保存未核对draft。

未执行云推理、修改模型或操作手机；用户提供的DeepSeek资料长度/厂商context信息不是本实现的硬编码依据。父端独立oneshot真实验收由其单独记录，不用离线测试替代。
