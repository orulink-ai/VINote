import hashlib

from app.llm.openai_llm import _BasePromptLLM
from app.services.tracing_service import traced_generation, record_usage, record_model_parameters, update_current, content_summary
from app.services.vilab_cloud_service import VILabCloudService
from app.llm.video_material import video_user_content


class VILabLLM(_BasePromptLLM):
    def __init__(self, user_id: str, model: str):
        self.user_id = user_id
        self.model = model

    def _complete_review(self, *, system_prompt: str, user_prompt: str) -> str:
        # The user-selected, frozen model owns both generation and fact review.
        # A legacy reviewer preference never authorizes a different model.
        return self._complete(system_prompt=system_prompt, user_prompt=user_prompt)

    @traced_generation
    def _complete(self, *, system_prompt: str, user_prompt: str) -> str:
        # Dictation postprocessing intentionally rejects summarization and may restore
        # the input. Notes must use VILab Server's authenticated chat gateway instead.
        system_prompt += ("\n仅根据提供的原文整理。严禁补充原文未提供的日期、人物、时长、"
                          "决策、待办或结论；缺少信息时省略相应章节，不要推断。")
        record_model_parameters({"stream": True})
        update_current(metadata={"prompt_version": hashlib.sha256(system_prompt.encode()).hexdigest()[:16]})
        update_current(input=[{"role": "system", "content": content_summary(system_prompt)},
                              {"role": "user", "content": content_summary(user_prompt)}])
        data = VILabCloudService().request(self.user_id, "POST", "/openai/v1/chat/completions", json={
            "model": self.model, "stream": True,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": video_user_content(user_prompt)}],
        })
        record_usage(data.get("usage"))
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("VILab LLM returned no summary")
        return content.strip()
