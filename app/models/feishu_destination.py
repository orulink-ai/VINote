"""Additive delivery metadata; register with Base before init_db/create_all.

No columns are added to the existing feishu_deliveries table. The parent row
retains the immutable title/body and existing idempotency and recovery fields.
"""
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class FeishuDeliveryDestinationDB(Base):
    __tablename__ = "feishu_delivery_destinations"

    delivery_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("feishu_deliveries.id", ondelete="CASCADE"), primary_key=True,
    )
    snapshot: Mapped[str] = mapped_column(Text, default="{}")
    phase: Mapped[str] = mapped_column(String(32), default="pending_create")
    permission: Mapped[str] = mapped_column(Text, default='{"status":"pending"}')
    error_code: Mapped[str] = mapped_column(String(64), default="")


class FeishuPublishReceiptDB(Base):
    __tablename__ = "feishu_publish_receipts"
    owner: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("feishu_deliveries.id"))


class FeishuWriteBatchDB(Base):
    __tablename__ = "feishu_write_batches"
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("feishu_deliveries.id"), primary_key=True)
    offset: Mapped[str] = mapped_column(String(20), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
