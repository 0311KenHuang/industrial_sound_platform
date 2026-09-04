"""Database schema setup, compatibility migrations and demo initialization."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from ..core.auth import hash_password
from ..core.config import UPLOAD_DIR
from ..core.database import db
from ..report import build_report
from ..services.catalog import row_dict
from ..services.diagnosis import alert_level, severity_for
from ..signal import CLASS_NAMES


def normalize_legacy_severity(connection: sqlite3.Connection) -> None:
    """Keep historical records on the same severity vocabulary as new diagnoses."""
    rechecks = {
        "正常": "7 天内复检",
        "轻度": "72 小时内复检",
        "中度": "24 小时内复检",
        "重度": "立即复检",
    }
    diagnoses = connection.execute("SELECT id, fault, report FROM diagnoses").fetchall()
    for item in diagnoses:
        severity = severity_for(item["fault"])
        report_text = item["report"]
        try:
            report = json.loads(report_text)
            if isinstance(report, dict):
                report["severity"] = severity
                report["recommended_recheck"] = rechecks.get(
                    severity, "24 小时内复检"
                )
                report_text = json.dumps(report, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
        connection.execute(
            "UPDATE diagnoses SET severity=?,report=? WHERE id=?",
            (severity, report_text, item["id"]),
        )
    alerts = connection.execute("SELECT id, diagnosis_id FROM alerts").fetchall()
    for item in alerts:
        diagnosis = connection.execute(
            "SELECT fault FROM diagnoses WHERE id=?", (item["diagnosis_id"],)
        ).fetchone()
        if diagnosis:
            severity = severity_for(diagnosis["fault"])
            connection.execute(
                "UPDATE alerts SET severity=?,level=? WHERE id=?",
                (severity, alert_level(severity), item["id"]),
            )


def normalize_workflow_state(connection: sqlite3.Connection) -> None:
    """Repair legacy links and statuses without producing notifications."""
    orders = connection.execute(
        """
        SELECT wo.id, wo.diagnosis_id, wo.alert_id, wo.status,
               wo.recheck_status,
               a.status AS alert_status
        FROM work_orders wo
        LEFT JOIN alerts a ON a.id = wo.alert_id
        """
    ).fetchall()
    for order in orders:
        if order["diagnosis_id"] is not None:
            connection.execute(
                "UPDATE diagnoses SET work_order_id=? "
                "WHERE id=? AND (work_order_id IS NULL OR work_order_id=?)",
                (order["id"], order["diagnosis_id"], order["id"]),
            )
        if order["alert_id"] is None:
            continue
        if order["alert_status"] == "已关闭":
            connection.execute(
                "UPDATE work_orders SET recheck_status='passed' WHERE id=?",
                (order["id"],),
            )
            continue
        if order["alert_status"] != "已关闭":
            connection.execute(
                "UPDATE alerts SET status='处理中' WHERE id=? AND status!='已关闭'",
                (order["alert_id"],),
            )
        if (
            order["status"] in ("处理中", "已完成")
            and order["recheck_status"] == "not_required"
        ):
            connection.execute(
                "UPDATE work_orders SET recheck_status='pending' WHERE id=?",
                (order["id"],),
            )


def seed_demo_history(connection: sqlite3.Connection) -> None:
    """Seed believable synthetic history on a new, empty installation."""
    if connection.execute("SELECT COUNT(*) FROM diagnoses").fetchone()[0]:
        return
    cases = [
        ("SC-LN-001", "normal", 0, "巡检基线样本"),
        ("SC-MJ-002", "imbalance", 1, "叶片积尘后复测"),
        ("SC-MH-003", "bearing_outer", 2, "高风速工况采样"),
        ("SC-GT-004", "gear_broken", 4, "边缘盒子上报样本"),
        ("SC-JL-005", "normal", 6, "月度例行巡检"),
    ]
    now = datetime.now()
    for index, (device_id, fault, days_ago, remark) in enumerate(cases):
        device = row_dict(
            connection.execute(
                "SELECT * FROM devices WHERE id=?", (device_id,)
            ).fetchone()
        )
        created_at = (now - timedelta(days=days_ago, hours=index)).isoformat(
            timespec="seconds"
        )
        confidence = {
            "normal": 0.96,
            "imbalance": 0.88,
            "bearing_outer": 0.91,
            "gear_broken": 0.94,
        }.get(fault, 0.85)
        probabilities = {
            name: round((1 - confidence) / (len(CLASS_NAMES) - 1), 4)
            for name in CLASS_NAMES
        }
        probabilities[fault] = confidence
        result = {
            "fault": fault,
            "probabilities": probabilities,
            "metrics": {
                "rms": 0.12 + index * 0.018,
                "peak": 0.48 + index * 0.04,
                "centroid_hz": 860 + index * 210,
                "rolloff_hz": 3100 + index * 350,
                "zero_crossing": 0.08,
            },
            "backend": "seed-demo-v1",
        }
        report = build_report(device, result)
        sample = connection.execute(
            "INSERT INTO audio_samples(device_id,file_name,duration,sample_rate,channel,collected_at,remark,uploaded_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                device_id,
                f"{device_id.lower()}-巡检-{days_ago}d.wav",
                10.0,
                16000,
                (index % 8) + 1,
                created_at,
                remark,
                created_at,
            ),
        )
        diagnosis = connection.execute(
            "INSERT INTO diagnoses(sample_id,device_id,fault,confidence,severity,features,model_version,report,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                sample.lastrowid,
                device_id,
                fault,
                confidence,
                severity_for(fault),
                json.dumps(
                    {"probabilities": probabilities, "metrics": result["metrics"]},
                    ensure_ascii=False,
                ),
                "seed-demo-v1",
                json.dumps(report, ensure_ascii=False),
                created_at,
            ),
        )
        if fault != "normal":
            alert_id = connection.execute(
                "INSERT INTO alerts(alert_code,diagnosis_id,device_id,level,severity,title,description,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    f"ALT-DEMO-{index + 1:03d}",
                    diagnosis.lastrowid,
                    device_id,
                    alert_level(severity_for(fault)),
                    severity_for(fault),
                    f"{report['fault_label']} · {device['name']}",
                    report["summary"],
                    "处理中" if fault == "bearing_outer" else "未处理",
                    created_at,
                ),
            ).lastrowid
            if fault == "gear_broken":
                order_code = f"WO-DEMO-{index + 1:03d}"
                order = connection.execute(
                    "INSERT INTO work_orders(order_code,diagnosis_id,alert_id,device_id,title,description,priority,status,assignee,assignee_id,recheck_status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        order_code,
                        diagnosis.lastrowid,
                        alert_id,
                        device_id,
                        "齿轮断齿 · 紧急检修",
                        report["possible_causes"],
                        "紧急",
                        "处理中",
                        "风场检修一组",
                        None,
                        "pending",
                        "system",
                        created_at,
                    ),
                )
                connection.execute(
                    "UPDATE diagnoses SET work_order_id=? WHERE id=?",
                    (order.lastrowid, diagnosis.lastrowid),
                )
                connection.execute(
                    "UPDATE alerts SET status='处理中' WHERE id=?", (alert_id,)
                )
                connection.execute(
                    "INSERT INTO work_order_logs(work_order_id,operator_id,action,from_status,to_status,remark,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        order.lastrowid,
                        "system",
                        "创建",
                        None,
                        "处理中",
                        "种子演示工单已派发",
                        created_at,
                    ),
                )


def init_db() -> None:
    """Create or upgrade the local SQLite database and seed a fresh install."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
              email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'operator', full_name TEXT NOT NULL,
              created_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS maintainers (
              id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
              phone TEXT NOT NULL, team TEXT NOT NULL DEFAULT '',
              is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, wind_farm TEXT NOT NULL DEFAULT '',
              province TEXT NOT NULL DEFAULT '四川省', city TEXT NOT NULL DEFAULT '', county TEXT NOT NULL DEFAULT '',
              device_type TEXT NOT NULL DEFAULT '风电机组',
              model TEXT NOT NULL DEFAULT 'SN-Standard', line TEXT NOT NULL DEFAULT 'A 产线',
              location TEXT NOT NULL, install_date TEXT, rated_params TEXT NOT NULL DEFAULT '{}',
              rated_power_kw REAL DEFAULT 0, hub_height_m REAL DEFAULT 0, rotor_diameter_m REAL DEFAULT 0,
              latitude REAL, longitude REAL,
              status TEXT NOT NULL, health INTEGER NOT NULL, last_seen TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audio_samples (
              id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL, file_path TEXT,
              file_name TEXT NOT NULL, duration REAL, sample_rate INTEGER, channel INTEGER DEFAULT 1,
              collected_at TEXT, collected_by INTEGER, remark TEXT, uploaded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diagnoses (
              id INTEGER PRIMARY KEY AUTOINCREMENT, sample_id INTEGER, work_order_id INTEGER,
              device_id TEXT NOT NULL,
              fault TEXT NOT NULL, confidence REAL NOT NULL, severity TEXT NOT NULL,
              features TEXT NOT NULL, model_version TEXT NOT NULL, report TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT, alert_code TEXT UNIQUE NOT NULL,
              diagnosis_id INTEGER NOT NULL, device_id TEXT NOT NULL, level TEXT NOT NULL,
              severity TEXT NOT NULL DEFAULT '中度', title TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, handled_at TEXT, handled_by TEXT, handle_remark TEXT
            );
            CREATE TABLE IF NOT EXISTS work_orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT, order_code TEXT UNIQUE NOT NULL,
              diagnosis_id INTEGER, alert_id INTEGER, device_id TEXT NOT NULL,
              title TEXT NOT NULL, description TEXT NOT NULL, priority TEXT NOT NULL,
              status TEXT NOT NULL, assignee TEXT NOT NULL, assignee_id INTEGER,
              recheck_status TEXT NOT NULL DEFAULT 'not_required', created_by TEXT NOT NULL,
              created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS work_order_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT, work_order_id INTEGER NOT NULL,
              operator_id TEXT NOT NULL, action TEXT NOT NULL, from_status TEXT,
              to_status TEXT NOT NULL, remark TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sms_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT, work_order_id INTEGER NOT NULL,
              maintainer_id INTEGER NOT NULL, event_type TEXT NOT NULL,
              phone TEXT NOT NULL, content TEXT NOT NULL,
              template_params TEXT NOT NULL DEFAULT '{}', provider TEXT NOT NULL,
              delivery_mode TEXT NOT NULL, status TEXT NOT NULL,
              provider_message_id TEXT, error_message TEXT,
              idempotency_key TEXT UNIQUE NOT NULL, triggered_by TEXT NOT NULL,
              sent_at TEXT, created_at TEXT NOT NULL
            );
            """
        )
        migrations = {
            "devices": {
                "wind_farm": "TEXT NOT NULL DEFAULT ''",
                "province": "TEXT NOT NULL DEFAULT '四川省'",
                "city": "TEXT NOT NULL DEFAULT ''",
                "county": "TEXT NOT NULL DEFAULT ''",
                "device_type": "TEXT NOT NULL DEFAULT '风电机组'",
                "model": "TEXT NOT NULL DEFAULT 'SN-Standard'",
                "install_date": "TEXT",
                "rated_params": "TEXT NOT NULL DEFAULT '{}'",
                "rated_power_kw": "REAL DEFAULT 0",
                "hub_height_m": "REAL DEFAULT 0",
                "rotor_diameter_m": "REAL DEFAULT 0",
                "latitude": "REAL",
                "longitude": "REAL",
                "is_active": "INTEGER NOT NULL DEFAULT 1",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            },
            "diagnoses": {
                "sample_id": "INTEGER",
                "work_order_id": "INTEGER",
                "severity": "TEXT NOT NULL DEFAULT '中度'",
                "features": "TEXT NOT NULL DEFAULT '{}'",
                "model_version": "TEXT NOT NULL DEFAULT 'prototype-v1'",
            },
            "alerts": {
                "alert_code": "TEXT",
                "level": "TEXT NOT NULL DEFAULT '警告'",
                "severity": "TEXT NOT NULL DEFAULT '中度'",
                "description": "TEXT NOT NULL DEFAULT ''",
                "handled_at": "TEXT",
                "handled_by": "TEXT",
                "handle_remark": "TEXT",
            },
            "work_orders": {
                "order_code": "TEXT",
                "alert_id": "INTEGER",
                "assignee_id": "INTEGER",
                "recheck_status": "TEXT NOT NULL DEFAULT 'not_required'",
                "description": "TEXT NOT NULL DEFAULT ''",
                "created_by": "TEXT NOT NULL DEFAULT 'system'",
                "completed_at": "TEXT",
            },
        }
        for table, columns in migrations.items():
            existing = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_diagnoses_work_order_id ON diagnoses(work_order_id);
            CREATE INDEX IF NOT EXISTS idx_work_orders_assignee_id ON work_orders(assignee_id);
            CREATE INDEX IF NOT EXISTS idx_work_orders_alert_id ON work_orders(alert_id);
            CREATE INDEX IF NOT EXISTS idx_sms_messages_work_order_id ON sms_messages(work_order_id);
            CREATE INDEX IF NOT EXISTS idx_sms_messages_status ON sms_messages(status);
            """
        )
        normalize_legacy_severity(connection)
        normalize_workflow_state(connection)
        if not connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            now = datetime.now().isoformat(timespec="seconds")
            connection.execute(
                "INSERT INTO users(username,email,password_hash,role,full_name,created_at) VALUES (?,?,?,?,?,?)",
                (
                    "admin",
                    "admin@soundnet.local",
                    hash_password("admin123"),
                    "admin",
                    "系统管理员",
                    now,
                ),
            )
        if not connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0]:
            now = datetime.now().isoformat(timespec="seconds")
            connection.executemany(
                "INSERT INTO devices(id,name,wind_farm,province,city,county,device_type,model,line,location,install_date,rated_params,rated_power_kw,hub_height_m,rotor_diameter_m,latitude,longitude,status,health,last_seen,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        "SC-LN-001",
                        "华能昭觉龙恩风电项目 01 号风机",
                        "华能昭觉风电项目",
                        "四川省",
                        "凉山州",
                        "昭觉县",
                        "风电机组",
                        "东方电气 DEW-D4200",
                        "龙恩项目 · A 区",
                        "四川省凉山州昭觉县（龙恩风电项目）",
                        "2024-06-18",
                        json.dumps(
                            {"rpm": 12.1, "generator": "永磁直驱", "voltage_kv": 35},
                            ensure_ascii=False,
                        ),
                        4200,
                        115,
                        172,
                        None,
                        None,
                        "online",
                        96,
                        now,
                        now,
                    ),
                    (
                        "SC-MJ-002",
                        "昭觉马觉风电项目 16 号风机",
                        "昭觉马觉风电项目",
                        "四川省",
                        "凉山州",
                        "昭觉县",
                        "风电机组",
                        "金风科技 GW155-4.5",
                        "马觉项目 · B 区",
                        "四川省凉山州昭觉县（马觉风电项目）",
                        "2025-03-21",
                        json.dumps(
                            {"rpm": 11.8, "generator": "半直驱", "voltage_kv": 35},
                            ensure_ascii=False,
                        ),
                        4500,
                        110,
                        155,
                        None,
                        None,
                        "online",
                        88,
                        now,
                        now,
                    ),
                    (
                        "SC-MH-003",
                        "普格马洪风电项目 08 号风机",
                        "普格马洪风电项目",
                        "四川省",
                        "凉山州",
                        "普格县",
                        "风电机组",
                        "明阳智能 MySE5.5-155",
                        "马洪项目 · C 区",
                        "四川省凉山州普格县（马洪风电项目）",
                        "2023-10-12",
                        json.dumps(
                            {"rpm": 10.9, "generator": "半直驱", "voltage_kv": 35},
                            ensure_ascii=False,
                        ),
                        5500,
                        120,
                        155,
                        None,
                        None,
                        "warning",
                        62,
                        now,
                        now,
                    ),
                    (
                        "SC-GT-004",
                        "普格甘天地风电场 22 号风机",
                        "普格甘天地风电场",
                        "四川省",
                        "凉山州",
                        "普格县",
                        "风电机组",
                        "远景能源 EN-192",
                        "甘天地风场 · A 区",
                        "四川省凉山州普格县（甘天地风电场）",
                        "2024-09-06",
                        json.dumps(
                            {"rpm": 9.8, "generator": "永磁直驱", "voltage_kv": 35},
                            ensure_ascii=False,
                        ),
                        6200,
                        125,
                        192,
                        None,
                        None,
                        "warning",
                        48,
                        now,
                        now,
                    ),
                    (
                        "SC-JL-005",
                        "三峡冕宁金林风电项目 31 号风机",
                        "三峡四川冕宁金林风电项目",
                        "四川省",
                        "凉山州",
                        "冕宁县",
                        "风电机组",
                        "运达 WD175-6250",
                        "金林项目 · D 区",
                        "四川省凉山州冕宁县（金林风电项目）",
                        "2025-01-28",
                        json.dumps(
                            {"rpm": 10.2, "generator": "永磁直驱", "voltage_kv": 35},
                            ensure_ascii=False,
                        ),
                        6250,
                        115,
                        175,
                        None,
                        None,
                        "online",
                        91,
                        now,
                        now,
                    ),
                ],
            )
            seed_demo_history(connection)
