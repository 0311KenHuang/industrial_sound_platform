"""Dashboard read models and model-training orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from ..core.database import db
from ..model import ModelManager
from ..services.catalog import row_dict
from ..signal import FAULTS


class DashboardService:
    """Build the aggregate payloads consumed by the dashboard frontend."""

    def __init__(self, model_manager: ModelManager) -> None:
        self.model_manager = model_manager

    def summary(self) -> Dict[str, Any]:
        with db() as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE is_active=1"
            ).fetchone()[0]
            normal = connection.execute(
                "SELECT COUNT(*) FROM devices WHERE is_active=1 AND status='online'"
            ).fetchone()[0]
            active_alerts = connection.execute(
                "SELECT COUNT(*) FROM alerts WHERE status!='已关闭'"
            ).fetchone()[0]
            open_orders = connection.execute(
                "SELECT COUNT(*) FROM work_orders WHERE status!='已关闭'"
            ).fetchone()[0]
            today = datetime.now().strftime("%Y-%m-%d")
            today_diagnoses = connection.execute(
                "SELECT COUNT(*) FROM diagnoses WHERE created_at LIKE ?",
                (today + "%",),
            ).fetchone()[0]
            done_orders = connection.execute(
                "SELECT COUNT(*) FROM work_orders WHERE status IN ('已完成','已关闭')"
            ).fetchone()[0]
            all_orders = connection.execute(
                "SELECT COUNT(*) FROM work_orders"
            ).fetchone()[0]
        return {
            "device_total": total,
            "normal_devices": normal,
            "abnormal_devices": total - normal,
            "today_diagnoses": today_diagnoses,
            "active_alerts": active_alerts,
            "open_work_orders": open_orders,
            "work_order_completion_rate": round(done_orders / all_orders, 4)
            if all_orders
            else 0,
        }

    def trend(self, days: int = 7) -> List[Dict[str, Any]]:
        result = []
        with db() as connection:
            for offset in range(days - 1, -1, -1):
                date = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
                row = connection.execute(
                    "SELECT COUNT(*) AS total, "
                    "SUM(CASE WHEN fault!='normal' THEN 1 ELSE 0 END) AS abnormal "
                    "FROM diagnoses WHERE created_at LIKE ?",
                    (date + "%",),
                ).fetchone()
                result.append(
                    {
                        "date": date,
                        "diagnoses": row["total"],
                        "abnormal": row["abnormal"] or 0,
                        "detection_rate": round(
                            (row["abnormal"] or 0) / row["total"], 4
                        )
                        if row["total"]
                        else 0,
                    }
                )
        return result

    def distribution(self) -> Dict[str, Any]:
        with db() as connection:
            fault = [
                dict(row)
                for row in connection.execute(
                    "SELECT fault AS name, COUNT(*) AS value "
                    "FROM diagnoses GROUP BY fault ORDER BY value DESC"
                )
            ]
            level = [
                dict(row)
                for row in connection.execute(
                    "SELECT level AS name, COUNT(*) AS value "
                    "FROM alerts GROUP BY level ORDER BY value DESC"
                )
            ]
            health = [
                dict(row)
                for row in connection.execute(
                    "SELECT status AS name, COUNT(*) AS value "
                    "FROM devices WHERE is_active=1 GROUP BY status"
                )
            ]
        for item in fault:
            item["label"] = FAULTS.get(item["name"], {}).get(
                "label", item["name"]
            )
        return {"fault_types": fault, "alert_levels": level, "health_status": health}

    def overview(self) -> Dict[str, Any]:
        summary = self.summary()
        with db() as connection:
            devices = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM devices WHERE is_active=1 ORDER BY id"
                )
            ]
            alerts_data = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM alerts ORDER BY id DESC LIMIT 8"
                )
            ]
            orders = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM work_orders ORDER BY id DESC LIMIT 8"
                )
            ]
            diagnoses_data = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM diagnoses ORDER BY id DESC LIMIT 8"
                )
            ]
        for item in diagnoses_data:
            item["fault_label"] = FAULTS.get(item["fault"], {}).get(
                "label", item["fault"]
            )
        return {
            "devices": devices,
            "alerts": alerts_data,
            "work_orders": orders,
            "diagnoses": diagnoses_data,
            "summary": summary,
            "model": {
                "ready": self.model_manager.backend is not None,
                "backend": self.model_manager.backend.name
                if self.model_manager.backend
                else "未训练",
                "samples": self.model_manager.trained_samples,
            },
            "faults": {name: data["label"] for name, data in FAULTS.items()},
        }

    def train(self) -> Dict[str, Any]:
        return self.model_manager.train(per_class=18)
