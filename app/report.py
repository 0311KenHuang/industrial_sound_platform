"""Template reports plus a drop-in Spark adapter."""
from __future__ import annotations

import os
import html
from datetime import datetime
from typing import Any

from .signal import FAULTS

CAUSES = {
    "normal": "当前声纹与健康基线一致，未发现明显异常。",
    "bearing_wear": "高频冲击与轴承特征频率能量升高，可能存在润滑不足、滚动体或滚道磨损。",
    "bearing_outer": "外圈特征频率附近冲击能量升高，可能存在滚道点蚀、疲劳剥落或润滑不足。",
    "bearing_inner": "内圈特征频率及其边带明显，可能存在内圈疲劳、偏载或安装同轴度问题。",
    "imbalance": "转频及其低阶谐波能量突出，可能存在转子质量偏心、积尘或联轴器对中偏差。",
    "misalignment": "二倍转频及高阶谐波突出，可能存在联轴器不对中、底座变形或轴向窜动。",
    "gear_fault": "啮合频率及边带能量异常，可能存在齿面磨损、断齿或润滑状态恶化。",
    "gear_broken": "啮合周期内出现强冲击，可能存在断齿、缺齿或齿面严重剥落。",
    "looseness": "半转频与多阶谐波明显，可能存在底座、连接件或轴承座松动。",
    "generator_fault": "工频及其倍频能量异常，可能存在电磁不平衡、绕组或散热系统异常。",
    "yaw_fault": "低频偏航特征与转频侧带升高，可能存在偏航驱动、制动器或齿圈异常。",
    "shaft_fault": "轴系二倍/四倍转频及高频谐波升高，可能存在主轴疲劳、裂纹或联接异常。",
}


class SparkAdapter:
    """Interface reserved for iFlytek Spark; no network call is made without credentials."""
    def __init__(self) -> None:
        self.enabled = all(os.getenv(key) for key in ("SPARK_APP_ID", "SPARK_API_KEY", "SPARK_API_SECRET"))

    def generate(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        # Real integration point: sign the WebSocket request and POST `payload` to Spark.
        # Keeping this method side-effect free makes offline demos deterministic.
        return None


def build_report(device: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    fault = diagnosis["fault"]
    confidence = float(diagnosis["probabilities"].get(fault, 0))
    metadata = FAULTS[fault]
    report = {
        "report_id": f"R-{datetime.now():%Y%m%d%H%M%S%f}"[:-3],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine": "template",
        "device": device,
        "fault_type": fault,
        "fault_label": metadata["label"],
        "severity": metadata["severity"],
        "confidence": round(confidence, 4),
        "summary": f"{device['name']} 当前诊断为“{metadata['label']}”，模型置信度 {confidence:.0%}。",
        "possible_causes": CAUSES[fault],
        "recommendations": [
            "保留本次声纹作为设备基线样本，安排 24 小时内复测。" if fault == "normal" else "建议立即创建检修工单，并在低负载状态下复核声纹。",
            "结合温度、转速、振动烈度与最近一次保养记录做交叉确认。",
            "完成处理后重新上传 10 秒以上录音，比较频谱峰值与 RMS 变化。",
        ],
        "signal_metrics": diagnosis["metrics"],
        "model_backend": diagnosis["backend"],
        "recommended_recheck": {
            "正常": "7 天内复检",
            "轻度": "72 小时内复检",
            "中度": "24 小时内复检",
            "重度": "立即复检",
        }.get(metadata["severity"], "24 小时内复检"),
    }
    spark = SparkAdapter().generate(report)
    if spark:
        report.update(spark)
    return report


def report_to_markdown(report: dict[str, Any]) -> str:
    metrics = report.get("signal_metrics", {})
    if not isinstance(metrics, dict): metrics = {}
    device = report.get("device", {})
    if not isinstance(device, dict): device = {}
    recommendations = "\n".join(f"{index}. {item}" for index, item in enumerate(report.get("recommendations", []), 1))
    confidence = float(report.get("confidence", 0) or 0)
    return f"""# 声网先知诊断报告\n\n- 报告编号：{report.get('report_id', '未编号')}\n- 生成时间：{report.get('generated_at', '未记录')}\n- 设备：{device.get('name', '未知设备')}（{device.get('id', '未知编号')}）\n- 诊断结论：**{report.get('fault_label', '未知')}**\n- 置信度：**{confidence:.0%}**\n- 严重程度：**{report.get('severity', '未评估')}**\n- 推荐复检：{report.get('recommended_recheck', '请安排复检')}\n\n## 频谱特征分析\n\n- RMS：{float(metrics.get('rms', 0) or 0):.4f}\n- 峰值：{float(metrics.get('peak', 0) or 0):.4f}\n- 频谱质心：{float(metrics.get('centroid_hz', 0) or 0):.1f} Hz\n- 85% 能量滚降：{float(metrics.get('rolloff_hz', 0) or 0):.1f} Hz\n\n## 可能原因\n\n{report.get('possible_causes', '暂无原因说明')}\n\n## 建议处理措施\n\n{recommendations or '1. 请结合现场工况进一步复核。'}\n\n> 本报告由 {report.get('engine', 'template')} 引擎生成，模型后端：{report.get('model_backend', '未记录')}。\n"""


def report_to_html(report: dict[str, Any]) -> str:
    safe = lambda value: html.escape(str(value))
    metrics = report.get("signal_metrics", {})
    if not isinstance(metrics, dict): metrics = {}
    device = report.get("device", {})
    if not isinstance(device, dict): device = {}
    rows = "".join(f"<tr><td>{safe(key)}</td><td>{safe(round(value, 4) if isinstance(value, (int, float)) else value)}</td></tr>" for key, value in metrics.items())
    recommendations = "".join(f"<li>{safe(item)}</li>" for item in report.get("recommendations", []))
    confidence = float(report.get("confidence", 0) or 0)
    return f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>声网先知诊断报告</title><style>body{{font:15px/1.7 Arial,'Microsoft YaHei',sans-serif;max-width:860px;margin:40px auto;padding:0 20px;background:#080807;color:#f7edda}}h1{{color:#f4c764}}h2{{color:#ffdc7e}}h3{{color:#d0a44c;border-bottom:1px solid #584622;padding-bottom:6px}}.hero{{background:#17130d;padding:24px;border:1px solid #8d6726;box-shadow:0 12px 30px #0008}}.muted{{color:#c9b485}}table{{border-collapse:collapse;width:100%;background:#100e0b}}td{{padding:9px;border-bottom:1px solid #49381d}}td:first-child{{color:#d0a44c;width:35%}}li{{margin:6px 0}}small{{color:#a89879}}</style><h1>声网先知 · 诊断报告</h1><div class='hero'><h2>{safe(report.get('fault_label', '未知诊断'))}</h2><p class='muted'>{safe(report.get('summary', '暂无摘要'))}</p><p>置信度：<b>{confidence:.0%}</b>　严重程度：<b>{safe(report.get('severity', '未评估'))}</b></p><p>推荐复检：{safe(report.get('recommended_recheck', '请安排复检'))}</p><p class='muted'>设备：{safe(device.get('name', '未知设备'))}（{safe(device.get('id', '未知编号'))}）</p></div><h3>频谱特征分析</h3><table>{rows or '<tr><td colspan="2">暂无特征数据</td></tr>'}</table><h3>可能原因</h3><p>{safe(report.get('possible_causes', '暂无原因说明'))}</p><h3>建议处理措施</h3><ol>{recommendations or '<li>请结合现场工况进一步复核。</li>'}</ol><hr><small>报告编号：{safe(report.get('report_id', '未编号'))} · 生成引擎：{safe(report.get('engine', 'template'))}</small></html>"""
