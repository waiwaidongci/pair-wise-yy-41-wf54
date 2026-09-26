from __future__ import annotations
from datetime import datetime, timezone
from .domain import ConflictError, NOTICE_MEASURES, ValidationError
TITLE='桥梁结构监测与限行决策'; ENTITY='桥梁告警'; NOTICE_ENTITY='交通通告'; ID_PREFIX='BM'
SEVERITIES=['normal', 'watch', 'warning', 'critical']; STATES=['normal', 'warning', 'restricted', 'closed', 'restored']; TRANSITIONS={'normal': ['warning'], 'warning': ['restricted'], 'restricted': ['closed'], 'closed': ['restored'], 'restored': []}; TRANSITION_ROLES={'warning': ['sensor_operator'], 'restricted': ['bridge_engineer'], 'closed': ['traffic_authority'], 'restored': ['bridge_engineer']}
CREATE_ROLES=set(['sensor_operator']); RECORD_ROLES=set(['sensor_operator', 'bridge_engineer']); AUDIT_ROLES=set(['bridge_engineer', 'viewer']); VIEW_ROLES=set(['sensor_operator', 'bridge_engineer', 'traffic_authority', 'viewer']); NOTICE_ROLES=set(['traffic_authority'])
SEVERITY_WEIGHT={'normal': 1.0, 'watch': 3.0, 'warning': 6.0, 'critical': 9.0}; DEADLINE_HOURS={'normal': 72, 'watch': 24, 'warning': 8, 'critical': 4}; TERMINAL_STATES=set(['restored'])
def priority_score(severity,quantity=0.0,threshold=1.0,open_records=0):
    if severity not in SEVERITY_WEIGHT: raise ValidationError("unknown severity")
    ratio=quantity/threshold if threshold>0 else 1.0
    return max(0,min(10,int(round(SEVERITY_WEIGHT[severity]+min(4.0,ratio*4.0)+min(3.0,float(open_records))))))
def response_deadline_hours(severity,quantity=0.0,threshold=1.0):
    if severity not in DEADLINE_HOURS: raise ValidationError("unknown severity")
    ratio=quantity/threshold if threshold>0 else 1.0
    return max(1,int(DEADLINE_HOURS[severity]/max(1.0,ratio)))
def escalation_required(severity,quantity=0.0,threshold=1.0):
    return severity==SEVERITIES[-1] or (threshold>0 and quantity>=threshold)
def can_transition(current,target): return target in TRANSITIONS.get(current,[])
def validate_transition(current,target):
    if current not in STATES or target not in STATES: raise ValidationError("未知状态")
    if not can_transition(current,target): raise ConflictError(f"不能从{current}转换到{target}")
def completion_blockers(target,open_records): return ["仍有未关闭事项"] if target in TERMINAL_STATES and open_records>0 else []
def role_for_transition(target): return set(TRANSITION_ROLES.get(target,[]))
MEASURE_LABELS={'restricted': '限行', 'closed': '封闭', 'restored': '恢复通行'}
def notice_required_for(target): return target in NOTICE_MEASURES
def _parse_time(value):
    dt=datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
def notice_blockers(target,notices,now=None):
    if not notice_required_for(target): return []
    now=now or datetime.now(timezone.utc)
    label=MEASURE_LABELS[target]
    matching=[n for n in notices if n['measure']==target]
    if not matching: return [f"缺少当前生效的{label}通告"]
    lifted=expired_or_pending=False
    for n in matching:
        if n.get('lifted_at'): lifted=True; continue
        if _parse_time(n['effective_from'])>now: expired_or_pending=True; continue
        if n.get('effective_to') and _parse_time(n['effective_to'])<now: expired_or_pending=True; continue
        return []
    if lifted and not expired_or_pending: return [f"{label}通告已解除，需重新发布"]
    return [f"{label}通告未生效或已过截止时间"]
