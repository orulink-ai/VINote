# 会议总结来源绑定与命题计账 protocol 2

范围：summary LLM 小模块、提示和离线测试。同一分支；不涉及 UI、媒体、模型连接、ASR、provider 调度或历史回执改写。没有真实模型运行或质量达标声明。

## 可执行链路

现有显式详略/形式请求仍为一次自动 draft、一次完整原始来源 review。新 draft 必须返回 `protocol:2`；不接受降级到没有来源片段的 v1 作为新候选。旧结果默认仍可按 v1 解析；不迁移、不重放、不改变失败状态。请求 API、模型快照与私有诊断文件外层协议不变。

`source_references.bind_source_references` 冻结每个真实 ASR 窗口的原始 `segment.text`，与时间前缀、独立 speaker 时间轴及诊断文字分离。ContextVar 保证嵌套恢复和并发隔离。两次调用仍获得原有完整转写和全部按既有能力允许的真实帧；没有新增推理调用、能力探测或重新采样。

`meeting_fact_protocol.py` 负责新协议；`meeting_fact_material.py` 仅分派 v1/v2。draft 核心结构：

```json
{
  "protocol": 2,
  "topics": [{"id": "T1", "title": "来自来源的主题"}],
  "facts": [{
    "id": "F1", "topic_id": "T1", "entity": null,
    "claims": [{
      "id": "C1", "field": "condition", "text": "独立命题",
      "anchor": "原样来源中的关键词组", "material": true,
      "evidence": [{"kind": "asr_span", "source_ref": "[ASR:0001]", "quote": "原样连续且唯一的来源片段"}]
    }]
  }]
}
```

field 为 entity/relation/attribute/quantity/condition/deadline/status。命题 ID 在本次材料内唯一。已命名 entity 须有其自身 entity claim 的原样 anchor；未知实体用 null，不连带否定其独立有据属性。每条 claim 自有来源与 material 状态，不要求每帧出事实，不输出全量 coverage 矩阵。

## 严格来源边界

- `asr_span` 的 quote 必须在该真实原始 ASR 窗口原样出现一次；不做任何空白、大小写、数字或标点规范化。重复或重叠重复的 quote 需提供精确 start/end（Python 字符下标，非 bool）。拒绝借用别的窗口或装饰后的 speaker/时间文字。
- claim.anchor 必须原样存在于它实际绑定的 quote 或视觉 observation 中。来源编号单独存在不能代替片段；`source_refs` 由有效绑定派生，仅为索引。
- `ocr_span` 仅接受实际 recognized OCR 的精确片段。OCR unavailable 不授权模型自造“已验证 OCR”。
- `frame_observation` 要求既有输入能力允许实际图像，并绑定真实 frame；验证标记始终是 `model_visual_observation`。图中文字、连线和实体解释仍是模型判断，不是本地证实的识别正确性。

**这些规则证明来源片段存在及地址一致，不证明 ASR 本身正确、语义蕴含或图片理解正确。** anchor 的存在也不证明命题全部关系成立。

## 复核、局部拒绝与正文

review 返回 `protocol:2, blocks:[{id,markdown}], audit:[{claim_id,disposition,block_ids}], figures:[]`。正文按 blocks 顺序以两个换行连接，仅保留模型写出的文字，内部 ID 不显示；audit 不再复抄长段落。每个 included 指向真实 block ID；这检查引用关系，不能机械证明该段表达了完整命题。

每条 claim 必须且仅能处置一次。rejected 必须空 block_ids、受控 reason_code、具体非空 reason 和重新验证的 evidence，至少涉及该命题自己的来源；不能整 fact 一行拒绝。`unclear_entity` 只用于 entity claim，不能借实体不明拒掉 quantity/condition/deadline。其他受控理由仍由模型作语义判断，不能把有片段的理由视为事实裁决正确。

详细版仍禁止把有效 material claim 标 omitted_for_depth。brief/concise 保留显式选择理由。review 可用 additional_facts/additional_topics 按同一严格来源规则补回 draft 遗漏；新命题同样完整计账。topic_audit 可选；提供时严格核验 ID、block 引用或理由，不再复抄正文。

图文使用 `{frame_ref,claim_ids,after_block_id,caption}`。只有真实 frame、已 included 命题、该 block 的关联全部成立，且 block 原文在最终正文 exact 且唯一时，才转换为既有 renderer 的 `after_passage/fact_ids`。一个 block 至多一张选图；无合适帧明确未完成。渲染器、真实图片 hash 核验及 export/HTML 流程未改。

## 调度及评分读取

主线程只能对明确的新 operation 调用现有 runner。无自动补调用、provider 重试、ASR 或旧 unknown/失败重放。两场并发的离线测试各自只发两次模型 stub 请求，来源和返回状态不互串。

raw 工作稿仍在解析前保存，raw review 仍在验证失败时保留。v2 raw review 的可评分正文为 `"\n\n".join(block["markdown"] for block in blocks).strip()`；这是确定性组装，不是人工改稿。校验失败不发布；有效正文可由独立评审者评价。旧 v1 的 markdown 字段读取不变。

仅使用全新合成命名、数值、条件和期限做反例；没有使用真实会议原稿、私有答案或评分报告作提示输入或测试期望。真实 provider 的 v2 产出接受性和质量分数尚待主线程明确调度后验证，离线通过不代表满分或可稳定交付。
