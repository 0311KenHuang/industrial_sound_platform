# 声网先知 · 工业声纹检测平台

一个不依赖外部数据与外部 API 的可运行 MVP。平台通过程序合成 12 类旋转设备声纹，提取频谱特征，使用可插拔分类器完成诊断，并用模板引擎生成结构化报告。若安装 PyTorch，会自动启用轻量 CNN；未安装时使用同一特征接口下的原型分类器，保证离线演示链路可运行。

## 快速启动

```powershell
cd industrial_sound_platform
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 。首次诊断或点击“训练模型”会生成本地合成数据并训练模型。

短信通知默认使用离线演示通道：工单分配、维修完成和复检通过关闭时会生成短信记录，页面会显示“消息已发送（演示通道）”并可查看完整正文；不会访问外部网络，也不会真实发送到手机。只有后续实现并配置具体供应商后，才应设置 `SOUNDNET_SMS_MODE` 切换真实通道。真实供应商未配置时会记录明确的失败状态，不会伪装成发送成功。

默认演示账号：`admin / admin123`。登录后才能访问设备、诊断、告警、工单、报告和模型训练接口；注册与登录接口保持公开。认证接口使用 JWT，生产环境请配置 `SOUNDNET_JWT_SECRET`；未配置时仅生成当前进程有效的随机密钥，服务重启后需要重新登录。密码优先使用 bcrypt 存储，缺少 bcrypt 时回退到 PBKDF2-SHA256。MP3 解析需要系统可用的 ffmpeg，WAV 无额外运行时要求。

初始种子库使用公开资料中的四川风电项目名称：华能昭觉风电项目、昭觉马觉风电项目、普格马洪风电项目、普格甘天地风电场、三峡四川冕宁金林风电项目。设备编号、机型参数和声纹读数是用于演示的模拟资产，不代表这些项目的真实 SCADA 编号或现场测量值；经纬度字段暂不填充，避免把估算位置伪装成精确坐标。

## 目录

- `app/signal.py`：合成声纹、WAV 解析、频谱特征
- `app/model.py`：模型热插拔接口、PyTorch CNN 与无依赖原型分类器
- `app/report.py`：模板化报告与星火接口适配层
- `app/main.py`：FastAPI API、SQLite 持久化、工单/复检/短信业务闭环
- `app/sms.py`：统一短信 Provider 接口、模板和离线演示 Provider
- `app/static/`：监控台前端

核心接口分组：`/api/auth/*`、`/api/devices`、`/api/maintainers`、`/api/diagnostics/*`、`/api/alerts/*`、`/api/work-orders/*`、`/api/sms-messages`、`/api/dashboard/*`。启动后可在 `/docs` 查看 Swagger 文档。除注册、登录和静态首页外，新增人员、短信和业务接口均要求登录。

工单关联告警时会同步为“处理中”；工单进入“已完成”后必须提交关联设备的复检诊断，复检正常才会关闭告警、关闭工单并按条件恢复设备状态。旧工单的自由文本负责人仍兼容，但没有 `assignee_id` 时不会发送短信。

## 替换真实模型或大模型

分类器只需实现 `fit()` 与 `predict()`，由 `ModelManager` 负责切换。报告层的 `SparkAdapter` 已固定请求数据结构与返回结构；配置 `SPARK_APP_ID`、`SPARK_API_KEY`、`SPARK_API_SECRET` 后即可接入真实服务，未配置时自动回退到模板报告。
