"""Execution-only meeting policy; historical reads never enter this guard."""
from contextvars import ContextVar
from functools import wraps

from fastapi import HTTPException

meeting_execution = ContextVar('vinote_meeting_execution', default=False)
MEETING_MODEL_ERROR = ('当前未配置可用的会议语音模型，尚未提交音频。请在设置中选择支持整段会议录音、'
                       '说话人分离和发言时间戳的模型；若目录中没有此类模型，请联系服务管理员配置。')

def is_meeting(options):
    return options.get('style') == 'meeting' or options.get('workflow') == 'meeting'

def require_public(source):
    from app.config import settings
    if (source.get('mode') != 'cloud' or
            (source.get('server_url') or '').rstrip('/') != settings.vilab_server_url.rstrip('/')):
        raise HTTPException(409, '会议处理仅支持固定公网模型服务，请在设置中选择服务模型后重新确认；原录制保留。')

def require_meeting_policy(policy):
    from app.services.adaptive_asr_policy import RecordingModelPolicy
    if not isinstance(policy, RecordingModelPolicy) or not policy.meeting_ready:
        raise HTTPException(409, MEETING_MODEL_ERROR)

def validate_meeting_source(owner, source, *, needs_stt=True):
    from app.services.adaptive_asr_policy import RecordingModelPolicy
    from app.services.vilab_cloud_service import VILabCloudService
    require_public(source)
    service = VILabCloudService()
    with service.task_snapshot(owner, snapshot=source):
        models = service.models(owner)
    if needs_stt:
        model = next((row for row in models if row.get('id') == source.get('asr_model')
                      and row.get('modelType') == 'asr'), None)
        try:
            policy = RecordingModelPolicy.from_capabilities(model.get('capabilities') if model else None)
        except ValueError:
            raise HTTPException(409, MEETING_MODEL_ERROR) from None
        require_meeting_policy(policy)
        service._validate_selection(models, source.get('asr_model'), 'asr')
    service._validate_selection(models, source.get('llm_model'), 'llm')

def meeting_pipeline(function):
    @wraps(function)
    def wrapped(self, **kwargs):
        from app.services.vilab_cloud_service import VILabCloudService
        meeting = kwargs.get('style') == 'meeting'
        if meeting:
            service = VILabCloudService()
            source = service.status(kwargs.get('user_id'))
            require_public(source)
            validate_meeting_source(kwargs.get('user_id'), source,
                                    needs_stt=kwargs.get('preloaded_transcript') is None)
        token = meeting_execution.set(meeting)
        try:
            if meeting:
                with service.task_snapshot(kwargs.get('user_id'), snapshot=source):
                    return function(self, **kwargs)
            return function(self, **kwargs)
        finally:
            meeting_execution.reset(token)
    return wrapped
