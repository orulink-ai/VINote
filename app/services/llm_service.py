"""
LLM configuration resolution and factory methods.
"""
from app.config import settings
from app.llm.base import LLMSummarizer
from app.llm.openai_llm import AnthropicLLM, AzureOpenAILLM, OpenAILLM
from app.models.model_profile import ResolvedLLMConfig
from app.services.model_profile_service import ModelProfileService


class LLMService:
    def __init__(self, model_profile_service: ModelProfileService | None = None):
        self.model_profile_service = model_profile_service or ModelProfileService()

    def resolve_config(
        self,
        *,
        user_id: str | None,
        model_profile_id: str | None,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
    ) -> ResolvedLLMConfig:
        resolved = self.model_profile_service.resolve_llm_config(
            user_id=user_id,
            model_profile_id=model_profile_id,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )
        if resolved:
            return resolved

        return ResolvedLLMConfig(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            model_name=settings.llm_model,
            api_key=settings.llm_api_key,
        )

    @staticmethod
    def build_summarizer(config: ResolvedLLMConfig) -> LLMSummarizer:
        if config.provider in {"openai-compatible", "groq-openai-compatible", "ollama"}:
            return OpenAILLM(api_key=config.api_key, base_url=config.base_url, model=config.model_name)
        if config.provider == "anthropic-compatible":
            return AnthropicLLM(api_key=config.api_key, base_url=config.base_url, model=config.model_name)
        if config.provider == "azure-openai":
            return AzureOpenAILLM(api_key=config.api_key, base_url=config.base_url, model=config.model_name)
        raise ValueError(f"Unsupported LLM provider: {config.provider}")

    def create_summarizer(
        self,
        *,
        user_id: str | None,
        model_profile_id: str | None,
        model_name: str | None,
        api_key: str | None,
        base_url: str | None,
    ) -> LLMSummarizer:
        if user_id:
            from app.services.vilab_cloud_service import VILabCloudService
            from app.llm.vilab_llm import VILabLLM

            cloud = VILabCloudService().status(user_id)
            if cloud["mode"] == "cloud" and cloud["llm_model"]:
                return VILabLLM(user_id, cloud["llm_model"])
            if cloud["mode"] == "cloud":
                raise ValueError("云端模式尚未选择笔记模型，请在设置中选择，或切换到本地模式")
            if model_profile_id == "vilab-cloud":
                model_profile_id = None
        config = self.resolve_config(
            user_id=user_id,
            model_profile_id=model_profile_id,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )
        from app.services.task_model_source import verify_local_config
        verify_local_config(user_id, "llm", config)
        return self.build_summarizer(config)
