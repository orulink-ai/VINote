"""Additive, device-owned illustrated publication journal; no legacy migration."""
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeishuNativeImagePlanDB(Base):
    __tablename__ = "feishu_native_image_plans"
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("feishu_deliveries.id"), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[str] = mapped_column(Text)


class FeishuNativeImageStepDB(Base):
    __tablename__ = "feishu_native_image_steps"
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("feishu_deliveries.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(20), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    result: Mapped[str] = mapped_column(Text, default="{}")
