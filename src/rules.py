from __future__ import annotations
from .domain import NOTICE_MEASURES, ConflictError, ValidationError
TITLE='桥梁结构监测与限行决策'; ENTITY='桥梁告警'; NOTICE_ENTITY='交通通告'; ID_PREFIX='BM'
SEVERITIES=['normal', 'watch', 'warning', 'critical']; STATES=['normal', 'warning', 'restricted', 'closed', 'restored']; TRANSITIONS={'normal': ['warning'], 'warning': ['restricted'], 'restricted': ['closed'], 'closed': ['restored'], 'restored': []}; TRANSITION_ROLES={'warning': ['sensor_operator'], 'restricted': ['bridge_engineer'], 'closed': ['traffic_authority'], 'restored': ['bridge_engineer']}
CREATE_ROLES=set(['sensor_operator']); RECORD_ROLES=set(['sensor_operator', 'bridge_engineer']); AUDIT_ROLES=set(['bridge_engineer', 'viewer']); VIEW_ROLES=set(['sensor_operator', 'bridge_engineer', 'traffic_authority', 'viewer']); NOTICE_ROLES=set(['traffic_authority'])
MEASURE_LABELS={'restriction': '限行', 'closure': '封闭', 'recovery': '恢复'}; NOTICE_TARGET_MEASURE={'restricted': 'restriction', 'closed': 'closure', 'restored': 'recovery'}
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
def required_notice_measure(target): return NOTICE_TARGET_MEASURE.get(target)
def notice_effective(notice,now):
    return bool(notice) and not notice.get("lifted_at") and notice["effective_from"]<=now<=notice["effective_to"]
def notice_blockers(target,notice,now):
    measure=required_notice_measure(target)
    if measure is None: return []
    label=MEASURE_LABELS[measure]
    if notice is None: return [f"缺少生效的{label}通告"]
    if notice.get("lifted_at"): return [f"{label}通告{notice['notice_no']}已解除"]
    if now<notice["effective_from"]: return [f"{label}通告{notice['notice_no']}尚未生效"]
    if now>notice["effective_to"]: return [f"{label}通告{notice['notice_no']}已过期"]
    return []
def role_for_transition(target): return set(TRANSITION_ROLES.get(target,[]))
