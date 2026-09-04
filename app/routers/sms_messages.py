from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from ..core.auth import current_user
from ..services.sms_messages import SmsMessageService


def create_router(service: SmsMessageService) -> APIRouter:
    router = APIRouter(prefix="/api/sms-messages", tags=["sms-messages"])

    @router.get("")
    def list_sms_messages(
        work_order_id: Optional[int] = Query(None, ge=1),
        status: Optional[str] = None,
        created_from: Optional[str] = None,
        created_to: Optional[str] = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=200),
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.list_messages(
            work_order_id,
            status,
            created_from,
            created_to,
            page,
            page_size,
        )

    @router.post("/{message_id}/retry")
    def retry_sms(
        message_id: int,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.retry_message(message_id, user)

    @router.get("/{message_id}")
    def get_sms_message(
        message_id: int,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.get_message(message_id)

    return router
