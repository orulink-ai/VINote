from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import session_scope
from app.db_models import UserPreferenceDB
from app.models.preferences import LanguageCode, PreferenceResponse

_VALID_LANGUAGES: frozenset[str] = frozenset({"en", "zh-CN"})


def _normalize_language(raw: str | None) -> LanguageCode | None:
    if raw in _VALID_LANGUAGES:
        return raw  # type: ignore[return-value]
    return None


def _resolve_visual_slides_auto(record: UserPreferenceDB | None) -> bool:
    if record is not None and record.visual_slides_auto_generate is not None:
        return bool(record.visual_slides_auto_generate)
    return bool(settings.visual_slides_auto_generate)


def _to_response(record: UserPreferenceDB | None) -> PreferenceResponse:
    return PreferenceResponse(
        language=_normalize_language(record.language if record else None),
        visual_slides_enabled=bool(settings.visual_slides_enabled),
        visual_slides_auto_generate=_resolve_visual_slides_auto(record),
    )


class PreferenceRepository:
    def get_preferences(self, user_id: str) -> PreferenceResponse:
        with session_scope() as db:
            record = db.get(UserPreferenceDB, user_id)
            return _to_response(record)

    def visual_slides_auto_generate_enabled(self, user_id: str) -> bool:
        if not settings.visual_slides_enabled:
            return False
        with session_scope() as db:
            record = db.get(UserPreferenceDB, user_id)
            return _resolve_visual_slides_auto(record)

    def update_preferences(
        self,
        user_id: str,
        *,
        language: LanguageCode | None = None,
        visual_slides_auto_generate: bool | None = None,
    ) -> PreferenceResponse:
        with session_scope() as db:
            record = db.get(UserPreferenceDB, user_id)
            if not record:
                try:
                    with db.begin_nested():
                        record = UserPreferenceDB(
                            user_id=user_id,
                            language=language if language is not None else "",
                            visual_slides_auto_generate=visual_slides_auto_generate,
                        )
                        db.add(record)
                        db.flush()
                except IntegrityError:
                    record = db.get(UserPreferenceDB, user_id)
                    if record is None:
                        raise
                    if language is not None:
                        record.language = language
                    if visual_slides_auto_generate is not None:
                        record.visual_slides_auto_generate = visual_slides_auto_generate
                    db.flush()
            else:
                if language is not None:
                    record.language = language
                if visual_slides_auto_generate is not None:
                    record.visual_slides_auto_generate = visual_slides_auto_generate
                db.flush()
            return _to_response(record)

    def set_language(self, user_id: str, language: LanguageCode) -> PreferenceResponse:
        return self.update_preferences(user_id, language=language)
