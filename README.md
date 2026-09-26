# 桥梁结构监测与限行决策

融合传感、巡检、交通荷载和天气数据，生成限载限行或恢复建议。

## 模块结构

- `app.py`：参数解析、依赖组装和HTTP服务启动。
- `src/domain.py`：数据结构、错误、状态和基础校验（含通告时间格式）。
- `src/rules.py`：状态机、角色矩阵、优先级、期限、关闭不变量和通告生效判断。
- `src/repository.py`：SQLite建表、自动升级（user_version）、事务、版本控制和审计链。
- `src/service.py`：权限检查、用例编排、并发控制和审计。
- `src/http_api.py`：JSON路由和统一错误响应。
- `src/audit.py`：UTC时间和SHA-256审计事件。
- `static/index.html`：最小演示页。
- `tests/`：完整流程、规则和失败测试。

## 初始化与启动

```bash
python3 app.py --db ./data.db --port 8318
```

默认端口为`8318`，首次启动自动建库。使用`X-Actor`和`X-Role`请求头传递身份。

## 主要接口

- `GET /health`
- `GET /api/items`
- `POST /api/items`
- `GET /api/items/{id}`
- `POST /api/items/{id}/records`
- `POST /api/items/{id}/transition`，必须提交`expected_version`
- `GET /api/audit`
- `POST /api/notices`：发布交通通告（`notice_no`、`issuer`、`measure`、`effective_from`，可选`effective_to`、`lifted_at`），仅traffic_authority，编号重复返回409
- `GET /api/notices`：通告列表，支持`?measure=restricted|closed|restored`过滤

允许角色：sensor_operator, bridge_engineer, traffic_authority, viewer。监测偏差与预警阈值之比和多条异常记录决定告警等级；限行与封闭决策必须绑定交通通告记录。

## 交通通告决策约束

- 告警进入`restricted`或`closed`前，必须存在对应措施且当前生效（已起算、未截止、未解除）的通告；缺失、过期或已解除返回409并说明原因，原状态与版本保持不变。
- 从`closed`恢复`restored`前，风险记录须全部关闭，且须有生效的恢复通行通告。
- 通告单独存于`notices`表，`notice_no`唯一；旧库启动后按`user_version`自动升级建表。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
