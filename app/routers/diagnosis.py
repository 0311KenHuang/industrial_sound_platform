from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from ..core.auth import current_user
from ..report import report_to_html, report_to_markdown
from ..schemas import EdgeReportRequest, SimulateRequest
from ..services.diagnoses import list_diagnoses
from ..services.diagnosis import DiagnosisService
from ..signal import FAULTS, synthesize


def create_router(service: DiagnosisService) -> APIRouter:
    router = APIRouter(tags=["diagnostics"])

    @router.post("/api/diagnose/simulate")
    @router.post("/api/diagnostics/simulate")
    def simulate(
        request: SimulateRequest,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        fault = request.fault
        if fault == "auto":
            fault = {
                "SC-LN-001": "normal",
                "SC-MJ-002": "imbalance",
                "SC-MH-003": "bearing_outer",
                "SC-GT-004": "gear_broken",
                "SC-JL-005": "normal",
            }.get(request.device_id, "normal")
        if fault not in FAULTS:
            raise HTTPException(400, "不支持的故障类型")
        signal, rate = synthesize(fault, seed=int(datetime.now().timestamp()))
        return service.run_signal_diagnosis(
            request.device_id,
            signal,
            rate,
            request.channel,
            request.remark or "程序合成演示样本",
            "synthetic.wav",
            request.work_order_id,
            user["username"],
            None if request.fault == "auto" else request.fault,
        )

    @router.post("/api/diagnose/upload")
    @router.post("/api/diagnostics/upload")
    async def diagnose_upload(
        device_id: str,
        channel: int = Query(1, ge=1, le=8),
        remark: str = "",
        work_order_id: Optional[int] = Query(None, ge=1),
        file: UploadFile = File(...),
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        extension = Path(file.filename or "").suffix.lower()
        raw = await file.read()
        if len(raw) > 50 * 1024 * 1024:
            raise HTTPException(413, "单个音频文件不能超过 50MB")
        try:
            signal, rate = service.decode_audio(raw, extension)
        except Exception as exc:
            raise HTTPException(400, f"音频读取失败：{exc}") from exc
        return service.run_signal_diagnosis(
            device_id,
            signal,
            rate,
            channel,
            remark,
            file.filename or "uploaded.wav",
            work_order_id,
            user["username"],
        )

    @router.post("/api/diagnostics/edge-report")
    def edge_report(
        request: EdgeReportRequest,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        if not request.audio_base64:
            raise HTTPException(400, "边缘上报需要 audio_base64 WAV 数据")
        try:
            signal, rate = service.decode_edge_audio(request.audio_base64)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return service.run_signal_diagnosis(
            request.device_id,
            signal,
            rate,
            request.channel,
            request.remark,
            "edge-report.wav",
            request.work_order_id,
            user["username"],
            request.fault_hint,
        )

    @router.get("/api/diagnostics")
    def diagnostics(
        device_id: Optional[str] = None,
        fault: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return list_diagnoses(device_id, page, page_size, fault)

    @router.get("/api/diagnoses/{diagnosis_id}")
    @router.get("/api/diagnostics/{diagnosis_id}")
    def diagnosis_detail(
        diagnosis_id: int,
        user: Dict[str, Any] = Depends(current_user),
    ) -> Dict[str, Any]:
        return service.get_diagnosis(diagnosis_id)

    def report_error_page(message: str) -> str:
        return (
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>报告暂不可用 · 声网先知</title>"
            "<style>body{font:15px/1.7 'Microsoft YaHei',sans-serif;"
            "background:#080807;color:#f7edda;max-width:720px;margin:80px auto;"
            "padding:0 24px}main{border:1px solid #8d6726;background:#17130d;"
            "padding:28px;box-shadow:0 12px 30px #0008}h1{color:#f4c764}"
            "p{color:#c9b485}</style><main><h1>报告暂不可用</h1>"
            f"<p>{html.escape(message)}</p>"
            "<p>请返回诊断历史重试，或重新生成一条诊断记录。</p>"
            "</main></html>"
        )

    @router.get(
        "/api/diagnostics/{diagnosis_id}/report",
        response_class=HTMLResponse,
    )
    def diagnosis_report(
        diagnosis_id: int,
        user: Dict[str, Any] = Depends(current_user),
    ) -> HTMLResponse:
        try:
            return HTMLResponse(report_to_html(service.report_payload(diagnosis_id)))
        except (KeyError, TypeError, ValueError) as exc:
            return HTMLResponse(report_error_page(str(exc)), status_code=422)

    @router.get("/api/diagnostics/{diagnosis_id}/report/export")
    def export_report(
        diagnosis_id: int,
        format: str = Query("markdown", pattern="^(markdown|html)$"),
        user: Dict[str, Any] = Depends(current_user),
    ) -> Response:
        try:
            report = service.report_payload(diagnosis_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            if format == "html":
                return Response(
                    report_to_html(report),
                    media_type="text/html",
                    headers={
                        "Content-Disposition": f"attachment; filename=report-{diagnosis_id}.html"
                    },
                )
            return Response(
                report_to_markdown(report),
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": f"attachment; filename=report-{diagnosis_id}.md"
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, f"报告内容无法导出：{exc}") from exc

    return router
