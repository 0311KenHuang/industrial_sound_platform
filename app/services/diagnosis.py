"""Diagnosis domain service.

The service owns model/audio/persistence orchestration.  HTTP routes provide
the service with the current user and leave notification delivery behind a
small callback so this module never imports the application entrypoint.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Union

import numpy as np
from fastapi import HTTPException

from ..core.database import db
from ..model import ModelManager
from ..report import build_report
from ..signal import CLASS_NAMES, FAULTS, build_visuals, read_wav
from .catalog import get_device, row_dict
from .workflow import recover_device_if_clear


def severity_for(fault: str) -> str:
    return FAULTS.get(fault, {}).get("severity", "重度")


def alert_level(severity: str) -> str:
    return {"轻度": "提示", "中度": "警告", "重度": "严重"}.get(severity, "提示")


SmsSender = Callable[[int, str, Union[str, Dict[str, Any]]], Dict[str, Any]]


class DiagnosisService:
    """Coordinate diagnosis execution while keeping external integrations injectable."""

    def __init__(
        self,
        model_manager: ModelManager,
        sms_sender: Optional[SmsSender] = None,
    ) -> None:
        self.model_manager = model_manager
        self.sms_sender = sms_sender

    def get_diagnosis(self, diagnosis_id: int) -> Dict[str, Any]:
        with db() as connection:
            row = connection.execute(
                "SELECT * FROM diagnoses WHERE id=?", (diagnosis_id,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "诊断记录不存在")
        return row_dict(row)

    def report_payload(self, diagnosis_id: int) -> Dict[str, Any]:
        detail = self.get_diagnosis(diagnosis_id)
        try:
            report = json.loads(detail.get("report") or "")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("诊断报告数据缺失或已损坏") from exc
        if not isinstance(report, dict):
            raise ValueError("诊断报告格式无效")
        return report

    def save_diagnosis(
        self,
        device_id: str,
        signal_size: int,
        sample_rate: int,
        channel: int,
        remark: str,
        result: Dict[str, Any],
        report: Dict[str, Any],
        file_name: str = "synthetic.wav",
        work_order_id: Optional[int] = None,
        triggered_by: str = "system",
    ) -> Dict[str, Any]:
        """Persist a diagnosis and, when requested, finish the recheck workflow."""
        device = get_device(device_id)
        now = datetime.now().isoformat(timespec="seconds")
        fault, confidence = result["fault"], float(result["probabilities"][result["fault"]])
        severity = severity_for(fault)
        duration = round(signal_size / max(sample_rate, 1), 2)
        recheck_result = None
        closed_order = False
        with db() as connection:
            recheck_order = None
            if work_order_id is not None:
                recheck_order = connection.execute(
                    "SELECT * FROM work_orders WHERE id=?", (work_order_id,)
                ).fetchone()
                if not recheck_order:
                    raise HTTPException(404, "复检关联工单不存在")
                if recheck_order["device_id"] != device_id:
                    raise HTTPException(400, "复检工单与设备不匹配")
                if recheck_order["status"] != "已完成":
                    raise HTTPException(409, "只有已完成工单可以提交复检结果")

            sample = connection.execute(
                "INSERT INTO audio_samples(device_id,file_name,duration,sample_rate,channel,collected_at,remark,uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                (device_id, file_name, duration, sample_rate, channel, now, remark, now),
            )
            diagnosis = connection.execute(
                "INSERT INTO diagnoses(sample_id,work_order_id,device_id,fault,confidence,severity,features,model_version,report,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    sample.lastrowid,
                    work_order_id,
                    device_id,
                    fault,
                    confidence,
                    severity,
                    json.dumps(
                        {"probabilities": result["probabilities"], "metrics": result["metrics"]},
                        ensure_ascii=False,
                    ),
                    result["backend"],
                    json.dumps(report, ensure_ascii=False),
                    now,
                ),
            )
            diagnosis_id = diagnosis.lastrowid
            alert = None
            if fault != "normal":
                code = f"ALT-{datetime.now():%Y%m%d%H%M%S}-{diagnosis_id}"
                alert = connection.execute(
                    "INSERT INTO alerts(alert_code,diagnosis_id,device_id,level,severity,title,description,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        code,
                        diagnosis_id,
                        device_id,
                        alert_level(severity),
                        severity,
                        f"{report['fault_label']} · {device['name']}",
                        report["summary"],
                        "未处理",
                        now,
                    ),
                ).lastrowid
                if work_order_id is not None:
                    connection.execute(
                        "UPDATE work_orders SET recheck_status='failed' WHERE id=?",
                        (work_order_id,),
                    )
                    connection.execute(
                        "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            work_order_id,
                            triggered_by,
                            "复检",
                            "已完成",
                            "已完成",
                            "复检结果异常，工单保持待复核状态",
                            now,
                        ),
                    )
                    recheck_result = "failed"
                health = (
                    max(22, int((1 - confidence) * 100))
                    if severity == "重度"
                    else max(45, int((1 - confidence) * 100))
                )
                connection.execute(
                    "UPDATE devices SET status='warning',health=?,last_seen=? WHERE id=?",
                    (health, now, device_id),
                )
            else:
                if work_order_id is not None:
                    linked_alert = (
                        connection.execute(
                            "SELECT id,status FROM alerts WHERE id=?",
                            (recheck_order["alert_id"],),
                        ).fetchone()
                        if recheck_order["alert_id"] is not None
                        else None
                    )
                    if linked_alert and linked_alert["status"] != "已关闭":
                        connection.execute(
                            "UPDATE alerts SET status='已关闭',handled_at=?,handled_by=?,handle_remark=? WHERE id=?",
                            (now, triggered_by, "复检通过", linked_alert["id"]),
                        )
                    connection.execute(
                        "UPDATE work_orders SET status='已关闭',recheck_status='passed',completed_at=COALESCE(completed_at,?) WHERE id=?",
                        (now, work_order_id),
                    )
                    connection.execute(
                        "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            work_order_id,
                            triggered_by,
                            "复检通过",
                            "已完成",
                            "已关闭",
                            "复检通过，工单闭环",
                            now,
                        ),
                    )
                    recheck_result = "passed"
                    closed_order = True
                recover_device_if_clear(connection, device_id, now)
        notifications = []
        if closed_order and work_order_id is not None:
            if self.sms_sender is None:
                raise RuntimeError("诊断服务尚未配置短信发送器")
            notifications.append(self.sms_sender(work_order_id, "closed", triggered_by))
        return {
            "id": diagnosis_id,
            "device_id": device_id,
            "sample_id": sample.lastrowid,
            "work_order_id": work_order_id,
            "created_at": now,
            "fault": fault,
            "severity": severity,
            **result,
            "alert_id": alert,
            "report": report,
            "recheck_result": recheck_result,
            "sms_notifications": notifications,
        }

    def run_signal_diagnosis(
        self,
        device_id: str,
        signal: Any,
        rate: int,
        channel: int,
        remark: str,
        file_name: str,
        work_order_id: Optional[int] = None,
        triggered_by: str = "system",
        fault_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        device = get_device(device_id)
        result = self.model_manager.predict(signal, rate)
        if fault_hint:
            if fault_hint not in FAULTS:
                raise HTTPException(400, "不支持的故障类型")
            probabilities = {
                name: max(float(value), 0.0)
                for name, value in result["probabilities"].items()
                if name in CLASS_NAMES
            }
            probabilities.setdefault(fault_hint, 0.0)
            target_confidence = 0.96
            other_names = [name for name in CLASS_NAMES if name != fault_hint]
            other_total = sum(probabilities.get(name, 0.0) for name in other_names)
            if other_total <= 0:
                other_total = float(len(other_names) or 1)
                probabilities.update({name: 1.0 for name in other_names})
            probabilities[fault_hint] = target_confidence
            for name in other_names:
                probabilities[name] = round(
                    (1 - target_confidence)
                    * probabilities.get(name, 0.0)
                    / other_total,
                    6,
                )
            result = {**result, "fault": fault_hint, "probabilities": probabilities}
        report = build_report(device, {**result, "severity": severity_for(result["fault"])})
        saved = self.save_diagnosis(
            device_id,
            len(signal),
            rate,
            channel,
            remark,
            result,
            report,
            file_name,
            work_order_id,
            triggered_by,
        )
        saved["visuals"] = build_visuals(signal, rate)
        saved["channel"] = channel
        return saved

    @staticmethod
    def decode_audio(raw: bytes, extension: str) -> Any:
        if extension in (".wav", ""):
            return read_wav(raw)
        if extension == ".mp3":
            try:
                from pydub import AudioSegment

                segment = AudioSegment.from_file(io.BytesIO(raw), format="mp3").set_channels(1)
                values = np.frombuffer(segment.raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                return values, segment.frame_rate
            except Exception as exc:
                raise ValueError(
                    "MP3 解析需要安装 pydub 并提供 ffmpeg；当前可直接上传 WAV"
                ) from exc
        raise ValueError("仅支持 WAV/MP3 音频")

    @staticmethod
    def decode_edge_audio(encoded: str) -> Any:
        try:
            return read_wav(base64.b64decode(encoded))
        except Exception as exc:
            raise ValueError(f"边缘音频解码失败：{exc}") from exc
