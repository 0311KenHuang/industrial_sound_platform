from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str
    password: str = Field(..., min_length=6)
    full_name: str = "运维人员"


class LoginRequest(BaseModel):
    username: str
    password: str


class DeviceRequest(BaseModel):
    id: str = Field(..., min_length=2, max_length=50)
    name: str
    wind_farm: str = ""
    province: str = "四川省"
    city: str = ""
    county: str = ""
    device_type: str = "电机"
    model: str = "SN-Standard"
    line: str = "A 产线"
    location: str = "待设置"
    install_date: Optional[str] = None
    rated_params: Dict[str, Any] = {}
    rated_power_kw: float = 0
    hub_height_m: float = 0
    rotor_diameter_m: float = 0
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SimulateRequest(BaseModel):
    device_id: str = "MTR-002"
    fault: str = "auto"
    channel: int = Field(1, ge=1, le=8)
    remark: str = ""
    work_order_id: Optional[int] = Field(None, ge=1)


class EdgeReportRequest(BaseModel):
    device_id: str
    audio_base64: Optional[str] = None
    fault_hint: Optional[str] = None
    channel: int = Field(1, ge=1, le=8)
    collected_at: Optional[str] = None
    remark: str = "边缘盒子上报"
    work_order_id: Optional[int] = Field(None, ge=1)


class MaintainerRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field(..., min_length=5, max_length=30)
    team: str = Field("", max_length=120)
    is_active: bool = True


class MaintainerUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    phone: Optional[str] = Field(None, min_length=5, max_length=30)
    team: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None


class WorkOrderRequest(BaseModel):
    diagnosis_id: Optional[int] = None
    alert_id: Optional[int] = None
    device_id: str
    title: str
    description: str = ""
    priority: str = "高"
    assignee: str = "待分配"
    assignee_id: Optional[int] = Field(None, ge=1)


class WorkOrderTransition(BaseModel):
    status: str = "已关闭"
    remark: str = ""
    assignee: Optional[str] = None
    assignee_id: Optional[int] = Field(None, ge=1)


class AlertHandleRequest(BaseModel):
    status: str
    remark: str = ""
