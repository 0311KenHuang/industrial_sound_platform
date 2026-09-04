from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .core.auth import current_user
from .core.bootstrap import init_db
from .core.config import STATIC_DIR
from .model import ModelManager
from .routers.auth import router as auth_router
from .routers.alerts import router as alerts_router
from .routers.dashboard import create_router as create_dashboard_router
from .routers.diagnosis import create_router as create_diagnosis_router
from .routers.devices import router as devices_router
from .routers.maintainers import router as maintainers_router
from .routers.sms_messages import create_router as create_sms_router
from .routers.work_orders import create_router as create_work_order_router
from .schemas import (
    WorkOrderRequest,
)
from .services.alerts import get_alert
from .services.diagnosis import DiagnosisService
from .services.dashboard import DashboardService
from .services.sms_messages import SmsMessageService
from .services.work_orders import WorkOrderService

model_manager = ModelManager()
sms_service = SmsMessageService()
diagnosis_service = DiagnosisService(model_manager, sms_sender=sms_service.send_work_order_sms)
work_order_service = WorkOrderService(
    sms_sender=sms_service.send_work_order_sms,
    sms_serializer=sms_service.message_dict,
)
dashboard_service = DashboardService(model_manager)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="声网先知 · 工业设备声纹预测性维护系统", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(auth_router)
app.include_router(alerts_router)
app.include_router(maintainers_router)
app.include_router(devices_router)
app.include_router(create_diagnosis_router(diagnosis_service))
app.include_router(create_work_order_router(work_order_service))
app.include_router(create_sms_router(sms_service))
app.include_router(create_dashboard_router(dashboard_service))


@app.get("/")
def index() -> FileResponse: return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/alerts/{alert_id}/convert-order")
def convert_alert(alert_id: int, user: Dict[str, Any] = Depends(current_user)) -> Dict[str, Any]:
    alert = get_alert(alert_id)
    return work_order_service.create_order(WorkOrderRequest(diagnosis_id=alert["diagnosis_id"], alert_id=alert_id, device_id=alert["device_id"], title=alert["title"], description=alert["description"], priority="紧急" if alert["level"] == "严重" else "高"), user)
