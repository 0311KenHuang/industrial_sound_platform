from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from ..core.auth import current_user
from ..services.dashboard import DashboardService


def create_router(service: DashboardService) -> APIRouter:
    router = APIRouter(tags=["dashboard"])

    @router.get("/api/dashboard/summary")
    def dashboard_summary(
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.summary()

    @router.get("/api/dashboard/trend")
    def dashboard_trend(
        days: int = Query(7, ge=7, le=30),
        user: Dict[str, Any] = Depends(current_user),
    ) -> List[Dict[str, Any]]:
        return service.trend(days)

    @router.get("/api/dashboard/distribution")
    def dashboard_distribution(
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.distribution()

    @router.get("/api/overview")
    def overview(
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.overview()

    @router.post("/api/train")
    def train(user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
        return {"ok": True, **service.train()}

    return router
