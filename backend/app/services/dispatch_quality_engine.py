"""Pure deterministic rule engine. No DB and no model calls."""
RULE_VERSION = "dispatch-quality-v2"
WEIGHTS = {"allocation": 35, "compliance": 25, "utilization": 15, "readiness": 10, "exceptions": 10, "traceability": 5}

def ratio(n, d):
    return min(max(n / d, 0), 1) if d > 0 else 0

def score_quality(metrics, issues, groups, trace_checks, *, target=.8, cancelled=False, critical_missing=False):
    evaluable = metrics['valid_demand_count'] > 0 and not cancelled and not critical_missing
    category_failures = {i['category'] for i in issues}
    scores = {
        "allocation": 20 * ratio(metrics['assigned_demand_count'], metrics['valid_demand_count']) + 15 * ratio(metrics['assigned_quantity'], metrics['valid_quantity']),
        "compliance": 25 * ratio(len(groups - category_failures), len(groups)),
        "utilization": 15 * min(metrics['average_load_ratio'] / target, 1) if metrics['trip_count'] else 0,
        "readiness": 10 * ratio(metrics['ready_trip_count'], metrics['trip_count']),
        "exceptions": 5 * (ratio(metrics['explained_unassigned_count'], metrics['unassigned_count']) if metrics['unassigned_count'] else 1) + 5 * (ratio(metrics['documented_failed_count'], metrics['exception_case_count']) if metrics['exception_case_count'] else 1),
        "traceability": 5 * ratio(sum(trace_checks.values()), len(trace_checks)),
    }
    total = round(sum(scores.values()), 2) if evaluable else None
    grade = next((name for bound, name in [(90,'A'),(80,'B'),(70,'C'),(60,'D'),(0,'E')] if total >= bound), None) if total is not None else None
    reasons = {
        "allocation": ["条数20×去重完整分配数/有效需求数；货量15×每需求封顶分配量/有效货量"],
        "compliance": ["25×通过的适用约束类别数/适用类别总数；明细问题均来自正式发布校验"],
        "utilization": [f"15×min(每趟封顶装载率均值/{target},1)；80%不是合规门槛"],
        "readiness": ["10×当前司机与快照一致且可出勤的趟次/总趟次；未确认代班不计可用"],
        "exceptions": ["5×未分配原因完整率 + 5×已记录失败原因的终态停靠点/全部异常案例；无异常第二项5分", "未分配数量不重复扣分；当前无异常工单处理状态，不推断已解决"],
        "traceability": ["5×通过的可验证数据项/检查项数：版本、审计、范围、任务关联、司机快照"],
    }
    deductions = {
        'allocation': [f"完整分配 {metrics['assigned_demand_count']} / {metrics['valid_demand_count']} 条；货量 {metrics['assigned_quantity']} / {metrics['valid_quantity']} kg"],
        'compliance': ["违规类别：" + '、'.join(sorted(category_failures & groups))] if category_failures & groups else (["没有任务，无适用约束可评分"] if not groups else []),
        'utilization': [f"封顶平均装载率 {metrics['average_load_ratio']:.2%}，参考目标 {target:.0%}；无任务时本项为零"],
        'readiness': [f"准备就绪 {metrics['ready_trip_count']} / {metrics['trip_count']} 趟，明细见司机准备状态"],
        'exceptions': [f"原因完整 {metrics['explained_unassigned_count']} / {metrics['unassigned_count']} 条；有失败原因的已处理停靠点 {metrics['documented_failed_count']} / {metrics['exception_case_count']} 个异常案例"],
        'traceability': ['未通过检查：' + '、'.join(k for k,v in trace_checks.items() if not v)] if not all(trace_checks.values()) else [],
    }
    return {"rule_version": RULE_VERSION, "status": "SCORED" if evaluable else "UNSCORABLE", "total_score": total, "grade": grade,
        "coverage": 1 if evaluable else 0, "utilization_target": target,
        "dimensions": [{"key": key, "max_score": maximum, "score": round(scores[key], 2), "deduction": round(maximum - scores[key], 2), "formula": reasons[key], "deduction_reasons": deductions[key] if scores[key] < maximum else []} for key, maximum in WEIGHTS.items()],
        "unscorable_reasons": (["方案已取消"] if cancelled else []) + (["没有有效需求"] if not metrics['valid_demand_count'] else []) + (["关键数据缺失或基准不一致"] if critical_missing else [])}
