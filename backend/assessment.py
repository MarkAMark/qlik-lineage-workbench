"""Transparent planning estimates, not measured migration delivery times."""
from __future__ import annotations

import re

from .script import strip_comments

RULES = [
    ('selection', r'\b(GetFieldSelections|GetSelectedCount|GetCurrentSelections|GetPossibleCount|GetExcludedCount)\s*\(',
     'very_high', 'Qlik 选择上下文', '设计 QuickSight 参数、筛选器与交互，并验证聚合粒度。'),
    ('security', r'\b(OSUser|QlikUser|Section\s+Access)\b',
     'very_high', '用户与权限逻辑', '重新设计 QuickSight 行级安全（RLS）；用不同角色验证数据可见性。'),
    ('aggr', r'\bAGGR\s*\(', 'high', '嵌套聚合 AGGR', '评估 PRE_AGG / PRE_FILTER 等 LAC 计算，或下推 SQL；核对粒度。'),
    ('set-analysis', r'\{\s*(?:\$|1|<|\$?\s*<)', 'high', 'Set Analysis', '逐项重建筛选与聚合上下文；验证选择状态和分母。'),
    ('window', r'\b(Above|Below|Before|After|RangeSum|Rank|RowNo|Peek|Previous)\s*\(',
     'high', '排序或窗口依赖', '用窗口函数、LAC 或 SQL 重写，并固定排序与分区规则。'),
    ('total', r'\b(?:NODISTINCT|TOTAL)\b', 'high', '特殊聚合粒度', '显式定义聚合层级，验证总计、去重与筛选语义。'),
    ('dynamic-expansion', r'\$\(\s*=', 'high', '运行时美元展开', '改为参数或预计算字段；静态导出无法确定运行时结果。'),
    ('variable', r'\$\(\s*[A-Za-z_]', 'medium', '变量展开', '区分常量、参数与表达式变量；按实际用途重构。'),
    ('qlik-function', r'\b(Only|Dual|Match|WildMatch|Pick|MaxString|MinString|Concat)\s*\(',
     'medium', 'Qlik 特有函数', '核实 QuickSight 对应能力；必要时下推 SQL，保留空值与多值语义。'),
    ('conditional', r'\bIF\s*\(', 'medium', '条件计算', '改写为 ifelse 或 SQL CASE，并验证空值、类型与计算粒度。'),
]
LEVELS = {'low': 0, 'medium': 1, 'high': 2, 'very_high': 3}
EXPRESSION_HOURS = {'low': 0.2, 'medium': 0.75, 'high': 2.0, 'very_high': 4.0}


def expression_parts(expression: str) -> list[str]:
    text = strip_comments(expression)
    parts = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        start = i
        if text[i] in "'\"`[":
            close = ']' if text[i] == '[' else text[i]
            i += 1
            while i < len(text):
                if text[i] == close:
                    i += 1
                    if i < len(text) and text[i] == close:
                        i += 1
                        continue
                    break
                i += 1
        else:
            match = re.match(r'[\w.]+|[^\s]', text[i:])
            i += match.end()
        parts.append(text[start:i])
    return parts


def risk(expression: str) -> dict:
    clean = strip_comments(expression)
    masked_code = ' '.join(' ' if part.startswith(("'", '"', '`', '[')) else part
                           for part in expression_parts(clean))
    issues = [dict(code=rule_code, level=level, title=title, action=action)
              for rule_code, pattern, level, title, action in RULES
              if re.search(pattern, clean if rule_code in ('dynamic-expansion', 'variable') else masked_code, re.I)]
    level = max((i['level'] for i in issues), key=lambda x: LEVELS[x], default='low')
    return dict(level=level, issues=issues, hours=EXPRESSION_HOURS[level],
                action=issues[0]['action'] if issues else '可优先验证基础维度或聚合，核对空值、格式与数据类型。')


def estimate(app, *, hours_per_day: float = 8, contingency: float = 25,
             productivity: float = 1) -> dict:
    if not 4 <= hours_per_day <= 12: raise ValueError('每天工时必须在 4–12 之间')
    if not 0 <= contingency <= 100: raise ValueError('缓冲比例必须在 0–100 之间')
    if not 0.5 <= productivity <= 3: raise ValueError('复杂度系数必须在 0.5–3 之间')
    unique = {}
    for field in app.fields.values():
        # Ignore formatting, while retaining whitespace inside field names and
        # literals. [Sales Amount] and [SalesAmount] are different Qlik fields.
        signature = tuple(expression_parts(field['expression']))
        unique.setdefault(signature, field['risk'])
    expression_hours = sum(r['hours'] for r in unique.values())
    sql_hours = sum(0.35 + b.get('joins', 0) * 0.08 + (0.4 if b.get('complex') else 0)
                    for b in app.parser.blocks if b['kind'] == 'sql')
    load_hours = sum(0.35 + (0.4 if b.get('mapping') else 0)
                     for b in app.parser.blocks if b['kind'] == 'load')
    components = [
        dict(name='应用梳理与数据集设计', hours=4.0),
        dict(name='Sheet 与布局重建', hours=len(app.sheets) * 1.5),
        dict(name='去重表达式重写', hours=round(expression_hours, 2)),
        dict(name='SQL 与 LOAD 改造', hours=round(sql_hours + load_hours, 2)),
        dict(name='变量与参数设计', hours=len(app.variables) * 0.2),
        dict(name='扩展组件替代', hours=len(app.extensions) * 2 + sum(app.extensions.values()) * 0.1),
    ]
    subtotal = sum(c['hours'] for c in components) * productivity
    qa = subtotal * 0.3
    likely = (subtotal + qa) * (1 + contingency / 100)
    unknown = len(app.parser.includes) + sum(f['status'] != 'complete' for f in app.fields.values())
    high_factor = 1.9 if unknown else 1.6
    counts = {level: sum(r['level'] == level for r in unique.values()) for level in LEVELS}
    return dict(appId=app.id, appName=app.name, components=components,
                qaHours=round(qa, 1), subtotalHours=round(subtotal, 1),
                lowDays=round(likely * 0.75 / hours_per_day, 1),
                likelyDays=round(likely / hours_per_day, 1),
                highDays=round(likely * high_factor / hours_per_day, 1),
                uniqueExpressions=len(unique), riskCounts=counts,
                highRisk=counts['high'] + counts['very_high'], unknowns=unknown,
                confidence='ROM / 待试迁移校准', hoursPerDay=hours_per_day,
                contingency=contingency, productivity=productivity,
                assumptions=['每 App 基础设计 4h；每 Sheet 布局 1.5h。',
                             '表达式按 App 内代码去重；低/中/高/很高复杂度分别为 0.2/0.75/2/4h。',
                             'SQL 块 0.35h + 每 JOIN 0.08h + 复杂语法 0.4h；LOAD 块 0.35h，Mapping 另加 0.4h。',
                             '每变量 0.2h；每扩展类型 2h + 每实例 0.1h；验证为实现工时的 30%。',
                             '下界为典型值 ×0.75；存在解析缺口时上界 ×1.9，否则 ×1.6。',
                             '不包含数据库视图内部改造、数据接入审批、平台搭建、性能容量与业务 UAT 等待。',
                             '未扣除跨 App 复用收益；先选代表性 Sheet 试迁移，再校准系数。'])
