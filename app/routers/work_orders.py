from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from ..core.auth import current_user
from ..schemas import WorkOrderRequest, WorkOrderTransition
from ..services.work_orders import WorkOrderService


def create_router(service: WorkOrderService) -> APIRouter:
    router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

    @router.get("")
    def work_orders(
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee: Optional[str] = None,
        assignee_id: Optional[int] = Query(None, ge=1),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=200),
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.list_orders(
            status,
            priority,
            assignee,
            assignee_id,
            page,
            page_size,
        )

    @router.post("")
    def create_work_order(
        request: WorkOrderRequest,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.create_order(request, user)

    @router.get("/{order_id}")
    def get_work_order(
        order_id: int,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.get_order(order_id)

    @router.put("/{order_id}/process")
    def process_work_order(
        order_id: int,
        request: WorkOrderTransition,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.process_order(order_id, request, user)

    @router.put("/{order_id}/assign")
    def assign_work_order(
        order_id: int,
        request: WorkOrderTransition,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        request.status = "处理中"
        return service.process_order(order_id, request, user)

    @router.put("/{order_id}/close")
    def close_work_order(
        order_id: int,
        request: WorkOrderTransition = WorkOrderTransition(status="已关闭"),
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        request.status = "已关闭"
        return service.process_order(order_id, request, user)

    return router
