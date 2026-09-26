# 桥梁结构监测与限行决策

融合传感、巡检、交通荷载和天气数据，生成限载限行或恢复建议。

## 模块结构

- `app.py`：参数解析、依赖组装和HTTP服务启动。
- `src/domain.py`：数据结构、错误、状态和基础校验。
- `src/rules.py`：状态机、角色矩阵、优先级、期限、关闭不变量和通告生效判断。
- `src/repository.py`：SQLite建表、事务、版本迁移和审计链。
- `src/service.py`：权限检查、用例编排、并发控制和审计。
- `src/http_api.py`：JSON路由和统一错误响应。
- `src/audit.py`：UTC时间和SHA-256审计事件。
- `static/index.html`：最小演示页。
- `tests/`：完整流程、规则和失败测试。

## 初始化与启动

```bash
python3 app.py --db ./data.db --port 8318
```

默认端口为`8318`，首次启动自动建库，旧库启动时按`user_version`自动迁移。使用`X-Actor`和`X-Role`请求头传递身份。

## 主要接口

- `GET /health`
- `GET /api/items`
- `POST /api/items`
- `GET /api/items/{id}`
- `POST /api/items/{id}/records`
- `POST /api/items/{id}/transition`，必须提交`expected_version`
- `GET /api/notices`，可按`?measure=`过滤
- `POST /api/notices`
- `POST /api/notices/{id}/lift`
- `GET /api/audit`

允许角色：sensor_operator, bridge_engineer, traffic_authority, viewer。监测偏差与预警阈值之比和多条异常记录决定告警等级；限行与封闭决策必须绑定交通通告记录。

## 交通通告

通告单独保存，字段包括编号`notice_no`（唯一，重复编号返回冲突）、发布单位`issuer`、措施`measure`（`restriction`限行/`closure`封闭/`recovery`恢复）、生效起止`effective_from`/`effective_to`和解除时间`lifted_at`。仅`traffic_authority`可发布和解除通告。

- 告警进入`restricted`/`closed`前，必须存在对应措施且当前生效的通告；通告缺失、尚未生效、已过期或已解除时返回409并说明原因，原状态保留。
- 从`closed`恢复`restored`前，风险记录须全部关闭，且须有生效的恢复通告。
- 每次状态变更的审计事件记录所依据的通告编号。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
