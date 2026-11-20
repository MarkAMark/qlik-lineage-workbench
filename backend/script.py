"""Conservative static lineage for Qlik scripts, backed by SQLGlot's Oracle AST.

Value dependencies are separate from join/filter context. No script is executed.
Unknown schemas, control flow and unsupported commands produce review boundaries.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, build_scope

from .model import Graph, Table, key
from .table_lineage import TableLineage


def strip_comments(text: str) -> str:
    # Preserve offsets, line numbers and strings (including // inside lib://).
    chars = list(text)
    i, quote = 0, ''
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = ''
            i += 1
            continue
        if c in "'\"`[":
            quote = ']' if c == '[' else c
            i += 1
        elif text[i:i + 2] in ('//', '--'):
            j = text.find('\n', i)
            j = len(text) if j < 0 else j
            chars[i:j] = ' ' * (j - i)
            i = j
        elif text[i:i + 2] == '/*':
            j = text.find('*/', i + 2)
            j = len(text) if j < 0 else j + 2
            for p in range(i, j):
                if chars[p] not in '\r\n':
                    chars[p] = ' '
            i = j
        else:
            i += 1
    return ''.join(chars)


@dataclass
class Statement:
    clean: str
    raw: str
    line: int
    end_line: int
    index: int

    @property
    def ref(self) -> dict:
        return dict(file='script.qvs', line=self.line, endLine=self.end_line)


def statements(text: str) -> list[Statement]:
    clean = strip_comments(text)
    result: list[Statement] = []
    start, i, quote, bracket = 0, 0, '', 0
    while i <= len(clean):
        c = clean[i] if i < len(clean) else ';'
        if quote:
            if c == quote:
                if i + 1 < len(clean) and clean[i + 1] == quote:
                    i += 2
                    continue
                quote = ''
        elif c in "'\"`":
            quote = c
        elif c == '[':
            bracket += 1
        elif c == ']':
            bracket = max(0, bracket - 1)
        elif c == ';' and not bracket:
            segment = clean[start:i]
            if segment.strip():
                offset = len(segment) - len(segment.lstrip())
                pos = start + offset
                result.append(Statement(segment.strip(), text[pos:min(i + 1, len(text))],
                                        text.count('\n', 0, pos) + 1,
                                        text.count('\n', 0, i) + 1, len(result)))
            start = i + 1
        i += 1
    return result


def split_columns(text: str) -> list[str]:
    parts: list[str] = []
    start, i, depth, bracket, quote = 0, 0, 0, 0, ''
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = ''
        elif c in "'\"`": quote = c
        elif c == '[': bracket += 1
        elif c == ']': bracket = max(0, bracket - 1)
        elif c == '(': depth += 1
        elif c == ')': depth -= 1
        elif c == ',' and depth == 0 and bracket == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def unquote(text: str) -> str:
    return text.strip().strip('[]"`')


def expression_refs(expression: str) -> list[tuple[str, str]]:
    """Keep quoted fields, functions, literals and dollar variables distinct.

    Dollar expansion also happens inside Qlik strings, including set searches.
    Unicode and mixed-case identifiers must not disappear from the lineage.
    """
    s = strip_comments(expression)
    refs = [(m.group(1), 'variable') for m in re.finditer(r'\$\(\s*([\w]+)', s)]
    s = re.sub(r'\$\(\s*[\w]+', '$(', s)
    i, braces = 0, 0
    while i < len(s):
        c = s[i]
        if c in "'\"`[":
            close = ']' if c == '[' else c
            start, value = i, []
            i += 1
            while i < len(s):
                if s[i] == close:
                    if i + 1 < len(s) and s[i + 1] == close:
                        value.append(close)
                        i += 2
                        continue
                    i += 1
                    break
                value.append(s[i])
                i += 1
            if c != "'" and not (c == '"' and braces):
                refs.append((''.join(value), 'field'))
            continue
        if c == '{': braces += 1
        elif c == '}': braces = max(0, braces - 1)
        number = re.match(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', s[i:])
        if number:
            i += number.end()
            continue
        name = re.match(r'(?:[^\W\d]|_)\w*(?:\.(?:[^\W\d]|_)\w*)*', s[i:])
        if name:
            end = i + name.end()
            if not re.match(r'\s*\(', s[end:]):
                refs.append((name.group(), 'identifier'))
            i = end
        else: i += 1
    return list(dict.fromkeys(refs))


def tokens(expression: str) -> list[str]:
    return list(dict.fromkeys(name for name, _ in expression_refs(expression)))


def top_level_words(text: str):
    """Clause keywords outside expressions and quoted strings/identifiers."""
    i, depth = 0, 0
    while i < len(text):
        c = text[i]
        if c in "'\"`[":
            close = ']' if c == '[' else c
            i += 1
            while i < len(text):
                if text[i] == close:
                    i += 1
                    if i < len(text) and text[i] == close:
                        i += 1
                        continue
                    break
                i += 1
            continue
        if c == '(': depth += 1
        elif c == ')': depth = max(0, depth - 1)
        match = re.match(r'[A-Za-z_]\w*', text[i:]) if depth == 0 else None
        if match:
            yield match.group().upper(), i, i + match.end()
            i += match.end()
        else: i += 1


def load_parts(stmt: Statement) -> tuple[str, str, str]:
    match = re.search(r'\bLOAD\s+(?:DISTINCT\s+)?', stmt.clean, re.I)
    assert match
    body = stmt.clean[match.end():]
    for word, start, end in top_level_words(body):
        if word in {'RESIDENT', 'INLINE', 'AUTOGENERATE', 'FROM'}:
            return body[:start].strip(), word.lower(), body[end:].strip()
        if word in {'WHERE', 'GROUP', 'ORDER'}:
            return body[:start].strip(), 'preceding', ''
    return body.strip(), 'preceding', ''


def load_column(item: str) -> tuple[str, str]:
    alias = re.search(r'\s+AS\s+(\[[^\]]+\]|"[^"]+"|[\w.]+)\s*$', item, re.I)
    return (item[:alias.start()].strip(), unquote(alias.group(1))) if alias else (item, unquote(item))


KEYWORDS = set('AS DISTINCT AND OR NOT NULL TRUE FALSE TOTAL NODISTINCT THEN ELSE END '
               'IF LOAD RESIDENT WHERE GROUP BY ORDER ASC DESC INLINE AUTOGENERATE '
               'FIELD FIELDS SET LET SQL SELECT FROM JOIN LEFT RIGHT INNER OUTER '
               'KEEP CONCATENATE NOCONCATENATE MAPPING OVER PARTITION ALL'.split())


class ScriptParser:
    def __init__(self, graph: Graph, variables: dict[str, str], namespace: str = '') -> None:
        self.graph = graph
        self.variables = variables
        self.tables: dict[str, Table] = {}
        self.warnings: list[dict] = []
        self.blocks: list[dict] = []
        self.references: dict[tuple[str, str], dict] = {}
        self.includes: list[dict] = []
        self.connection = ''
        self.last_table = ''
        self.field_cache: dict[str, str] = {}
        self.pending: list[tuple[Statement, str]] = []
        self.control_flow = False
        self.table_lineage = TableLineage(graph, namespace)

    def warn(self, code: str, message: str, ref: dict | None = None) -> None:
        self.warnings.append(dict(code=code, message=message, ref=ref))

    def missing(self, label: str, identity: str, ref: dict | None = None,
                note: str = '导出中未找到可确认的字段定义。') -> str:
        return self.graph.add('unresolved', identity, label, ref=ref,
                              confidence='unresolved', note=note)

    def source(self, table: str, column: str, ref: dict, *, source_type: str = 'database',
               confidence: str = 'parsed', note: str = '') -> str:
        if '$(' in table:
            confidence, note = 'review', '源路径依赖运行时展开，静态导出无法确认实际资产。'
        if source_type == 'database' and not self.connection:
            confidence = 'review'
            note = '已识别数据库表与列，但脚本未导出连接定义；需核实所属数据库。'
        return self.graph.add('source', (self.connection, table, column), f'{table}.{column}',
                              table=table, field=column, connection=self.connection,
                              sourceType=source_type, ref=ref, expression=column,
                              confidence=confidence, note=note)

    def resolve(self, field: str) -> str:
        if field in self.field_cache:
            return self.field_cache[field]
        matches = [table.fields[field] for table in self.tables.values() if field in table.fields]
        matches = list(dict.fromkeys(matches))
        confidence = 'parsed'
        note = ''
        if not matches:
            # Qlik field names are case-sensitive. Case-only alternatives are suggestions,
            # not lineage edges, since YEAR_MONTH and Year_Month can coexist.
            alternatives = sorted({n for t in self.tables.values() for n in t.fields
                                   if n.casefold() == field.casefold()})
            wildcards = [w for t in self.tables.values() for w in t.wildcards]
            message = '导出中未找到此字段的加载定义。'
            if alternatives: message += ' 存在大小写不同的字段：' + ', '.join(alternatives)
            if wildcards: message += ' 脚本包含未展开的 *，需要补充源表 schema。'
            unresolved = self.missing(field, ('model', field), note=message)
            self.field_cache[field] = unresolved
            return unresolved
        if len(matches) > 1:
            confidence = 'review'
            note = f'同名字段出现在 {len(matches)} 个逻辑表；显示全部静态来源，需核实 Qlik 关联语义。'
        node = self.graph.add('field', field, field, expression=field,
                              confidence=confidence, note=note,
                              tables=[t.name for t in self.tables.values() if field in t.fields])
        for parent in matches: self.graph.link(parent, node)
        self.field_cache[field] = node
        return node

    def bind(self, node: str, expression: str, context: Table | None = None,
             *, allow_unknown: bool = True, references: dict[str, str] | None = None) -> None:
        known_fields = {f for t in self.tables.values() for f in t.fields}
        if context: known_fields.update(context.fields)
        for token, ref_kind in expression_refs(expression):
            if ref_kind == 'variable' and token in self.variables:
                self.graph.link(self.variables[token], node)
            elif ref_kind != 'variable' and context and token in context.fields:
                self.graph.link(context.fields[token], node)
            elif ref_kind != 'variable' and context is None and token in known_fields:
                self.graph.link(self.resolve(token), node)
            elif ref_kind != 'variable' and references and token in references:
                self.graph.link(references[token], node, relation='measure-reference')
            elif ref_kind == 'identifier' and token in self.variables:
                self.graph.link(self.variables[token], node)
            elif allow_unknown and (ref_kind != 'identifier' or token.upper() not in KEYWORDS):
                parent = self.missing(token, ('expression', ref_kind, token), self.graph.nodes[node].get('ref'),
                                      note='引用的变量未导出。' if ref_kind == 'variable' else '导出中未找到可确认的字段定义。')
                self.graph.link(parent, node)
        for dynamic in re.findall(r'\$\(\s*=([^\n]+)', expression):
            self.graph.nodes[node]['confidence'] = 'review'
            self.graph.nodes[node]['note'] = '包含运行时美元展开；字段依赖为静态识别结果。'

    def parse(self, text: str) -> None:
        self.table_lineage.script = text
        for stmt in statements(text):
            s = stmt.clean
            include = re.search(r'\$\((?:Must_)?Include\s*=\s*(\[[^\]]+\]|[^)]*)\)', s, re.I | re.S)
            if include:
                item = dict(path=unquote(include.group(1)), ref=stmt.ref)
                self.includes.append(item)
                self.warn('missing-include', '外部 Include 未随导出提供：' + item['path'], stmt.ref)
                continue
            conn = re.search(r"\bLIB\s+CONNECT\s+TO\s+['\"]([^'\"]+)['\"]", s, re.I)
            if conn:
                self.connection = conn.group(1)
                continue
            assignment = re.match(r'\s*(SET|LET)\s+(\w+)\s*=\s*(.*)', s, re.I | re.S)
            if assignment:
                name, definition = assignment.group(2, 3)
                if name.startswith('v'):
                    if name not in self.variables:
                        self.variables[name] = self.graph.add('variable', name, name,
                                                              expression=definition, ref=stmt.ref,
                                                              note='脚本赋值表达式；未执行 LET。')
                    self.graph.nodes[self.variables[name]].setdefault('assignments', []).append(
                        dict(expression=definition, ref=stmt.ref))
                continue
            if re.search(r'(?im)^\s*(IF\s+.+\s+THEN|FOR\b|DO\b|SUB\b|CALL\b)', s):
                self.control_flow = True
                self.warn('control-flow', '存在条件、循环或子程序；未执行脚本，分支需人工核实。', stmt.ref)
            if re.search(r'(?im)^\s*(?:SQL\s+)?(?:CREATE|INSERT|UPDATE|DELETE|EXECUTE|EXEC)\b', s):
                self.warn('database-side-effect', '数据库 DDL/DML 为迁移依赖，未执行且未推断其字段血缘。', stmt.ref)
                continue
            dropped = re.search(r'(?ims)^\s*DROP\s+TABLES?\s+(.+)', s)
            if dropped:
                for name in split_columns(dropped.group(1)):
                    removed = self.tables.pop(unquote(name), None)
                    if removed:
                        self.table_lineage.drop(removed, stmt)
                continue
            dropped_fields = re.search(r'(?ims)^\s*DROP\s+FIELDS?\s+(.+)', s)
            if dropped_fields:
                field_part = dropped_fields.group(1)
                from_clause = next(((start, end) for word, start, end in top_level_words(field_part) if word == 'FROM'), None)
                selected = [unquote(x) for x in split_columns(field_part[from_clause[1]:])] if from_clause else list(self.tables)
                fields = field_part[:from_clause[0]] if from_clause else field_part
                for name in selected:
                    if name in self.tables:
                        previous = self.tables[name].lineage_id
                        for f in split_columns(fields): self.tables[name].fields.pop(unquote(f), None)
                        self.table_lineage.version(self.tables[name], 'DROP FIELDS', stmt,
                                                   [(previous, ['data'])], previous=previous)
                continue
            if re.search(r'(?im)^\s*(RENAME|QUALIFY|UNQUALIFY|BINARY|DERIVE)\b', s):
                self.warn('unsupported-script', '未支持的脚本命令；该部分字段关系需人工核实。', stmt.ref)
            labels = re.findall(r'(?m)^\s*(\[[^\]]+\]|[A-Za-z_][\w .-]*):\s*$', s)
            label = unquote(labels[-1]) if labels else ''
            sql_match = re.search(r'(?im)^\s*(?:SQL\s+)?(?=SELECT\b|WITH\b)', s)
            load_match = re.search(r'(?im)^\s*LOAD\b', s)
            if sql_match and (not load_match or sql_match.start() < load_match.start()):
                required = set()
                for pending_stmt, _ in reversed(self.pending):
                    columns, _, _ = load_parts(pending_stmt)
                    for item in split_columns(columns):
                        if item != '*':
                            value, _ = load_column(item)
                            required.update(token for token, kind in expression_refs(value)
                                            if kind != 'variable' and token not in self.variables
                                            and (kind == 'field' or token.upper() not in KEYWORDS))
                    if '*' not in split_columns(columns): break
                table = self.parse_sql(s[sql_match.end():], stmt, label or f'SQL_{stmt.index}', required)
                self.store_with_preceding(table, s, stmt, label)
            elif load_match:
                _, source_kind, _ = load_parts(stmt)
                if source_kind == 'preceding':
                    self.pending.append((stmt, label))
                else:
                    table = self.parse_load(stmt, label or f'LOAD_{stmt.index}')
                    self.store_with_preceding(table, s, stmt, label)
        for stmt, label in self.pending:
            self.warn('missing-preceding-source', '前置 LOAD 缺少后续数据源：' + label, stmt.ref)
        self.field_cache.clear()

    def store_with_preceding(self, table: Table, command: str, stmt: Statement, label: str) -> None:
        if self.pending:
            outer = self.pending[0][0]
            for pending_stmt, pending_label in reversed(self.pending):
                table = self.parse_load(pending_stmt, pending_label or label or table.name, table)
            self.pending.clear()
            command, stmt = outer.clean, outer
        self.store(table, command, stmt)

    def requested_star_columns(self, ast, required: set[str]) -> set[str]:
        """Materialize only columns explicitly referenced by a preceding LOAD.

        This is demand-driven projection, not a guessed database schema. A column
        must have one wildcard route to a physical table; multiple unknown stars
        remain unresolved. Known subquery/CTE outputs are followed recursively.
        """
        scope = build_scope(ast)
        added = set()
        if scope is None: return added

        def route(current: Scope, column: str, seen: set[int]):
            if id(current) in seen or not isinstance(current.expression, exp.Select): return None
            query = current.expression
            explicit = [p for p in query.selects if not p.is_star and p.alias_or_name == column]
            if explicit: return [] if len(explicit) == 1 else None
            candidates = []
            sources = current.selected_sources
            for projection in query.selects:
                if not projection.is_star: continue
                aliases = [projection.table] if isinstance(projection, exp.Column) and projection.table else list(sources)
                for alias in aliases:
                    if alias not in sources: continue
                    source = sources[alias][1]
                    if isinstance(source, exp.Table):
                        if '__QLIK_PARAMETER__' not in source.sql(): candidates.append((alias, []))
                    elif isinstance(source, Scope):
                        steps = route(source, column, seen | {id(current)})
                        if steps is not None: candidates.append((alias, steps))
            if len(candidates) != 1: return None
            alias, steps = candidates[0]
            return steps + [(query, alias)]

        for column in sorted(required):
            # Unquoted Oracle fields are uppercase; never rewrite Qlik casing.
            steps = route(scope, column, set())
            if steps:
                if column != column.upper(): continue
                for query, alias in steps:
                    if not any(not p.is_star and p.alias_or_name == column for p in query.selects):
                        query.select(exp.alias_(exp.column(column, table=alias), column), append=True, copy=False)
                added.add(column)
        return added

    def parse_sql(self, sql: str, stmt: Statement, name: str, required: set[str] | None = None) -> Table:
        table = Table(name)
        scope = None
        table_status = 'complete'
        # Dollar expansions are represented by a SQL placeholder, not evaluated.
        dynamic = bool(re.search(r'\$\(', sql))
        sql_input = re.sub(r'\$\([^()]*\)', '__QLIK_PARAMETER__', sql)
        self.blocks.append(dict(kind='sql', name=name, ref=stmt.ref,
                                joins=len(re.findall(r'\bJOIN\b', sql, re.I)),
                                complex=bool(re.search(r'\b(UNION|WITH|OVER|GROUP\s+BY)\b', sql, re.I))))
        try:
            ast = normalize_identifiers(sqlglot.parse_one(sql_input, read='oracle'), dialect='oracle')
            demanded = self.requested_star_columns(ast, required or set())
            qualified = qualify(ast, dialect='oracle', validate_qualify_columns=False,
                                identify=False, expand_stars=True)
            scope = build_scope(qualified)
            if scope is None: raise ValueError('No query scope')
            # Inventory includes predicate-only and wildcard inputs too. They are
            # not added as value-dependency edges for an unrelated output column.
            for nested in scope.traverse():
                physical = {}
                for alias, (_, source) in nested.selected_sources.items():
                    if isinstance(source, exp.Table):
                        source_name = '.'.join(part.name for part in source.parts)
                        if '__QLIK_PARAMETER__' in source_name: continue
                        identity = (self.connection, source_name)
                        physical[alias] = identity
                        self.references.setdefault(identity, dict(table=source_name, connection=self.connection,
                                                                   fields=set(), ref=stmt.ref))
                for col in nested.columns:
                    if col.table in physical:
                        self.references[physical[col.table]]['fields'].add(col.name)
            projections = qualified.selects
            for projection in projections:
                if projection.is_star:
                    table.wildcards.append(dict(sql=sql, ref=stmt.ref, connection=self.connection))
                    self.warn('wildcard-schema', 'SELECT * 缺少源 schema，字段不会被假定展开：' + name, stmt.ref)
                    continue
                column = projection.alias_or_name
                if not column: continue
                try:
                    # Projection names are already normalized. Preserve quoted
                    # mixed-case aliases instead of normalizing them a second time.
                    traced = lineage(exp.column(column, quoted=True), qualified, scope=scope, dialect='oracle', copy=False)
                    root = self.sql_node(traced, stmt, name, set())
                    table.fields[column] = root
                    self.graph.nodes[root]['field'] = column
                    self.graph.nodes[root]['table'] = name
                    if column in demanded:
                        self.graph.nodes[root]['wildcardResolved'] = True
                        self.graph.nodes[root]['note'] = '根据前置 LOAD 显式引用的字段名，沿唯一 SQL 通配符路径追溯；未假定完整源表 schema。'
                    if dynamic:
                        self.graph.nodes[root]['parameterized'] = True
                    if self.control_flow:
                        self.graph.nodes[root]['confidence'] = 'review'
                        self.graph.nodes[root]['note'] = '脚本含运行时控制流，需确认此加载块是否执行。'
                except Exception as error:
                    node = self.graph.add('sql', (stmt.index, column), f'{name}.{column}',
                                          expression=projection.sql(dialect='oracle', pretty=True),
                                          ref=stmt.ref, confidence='review',
                                          note='SQL 列级解析不完整：' + str(error)[:180], table=name, field=column)
                    parent = self.missing(column, ('sql-column', stmt.index, column), stmt.ref)
                    self.graph.link(parent, node)
                    table.fields[column] = node
            if not table.fields and not table.wildcards: raise ValueError('No output columns')
        except Exception as error:
            table.wildcards.append(dict(sql=sql, ref=stmt.ref, connection=self.connection))
            self.warn('sql-parse', f'SQL 解析失败，保留原始代码：{name} / {str(error)[:150]}', stmt.ref)
            table_status = 'partial'
        inputs = self.table_lineage.sql_inputs(scope, table, self.connection, stmt) if scope else []
        if not scope:
            unknown = self.table_lineage.source('未解析的 SQL 输入', self.connection, 'unresolved', stmt.ref)
            inputs = [(unknown, ['reference'])]
        self.table_lineage.stage(table, 'SQL', stmt, inputs,
                                 status='partial' if self.control_flow else table_status)
        return table

    def sql_node(self, traced, stmt: Statement, name: str, seen: set[int]) -> str:
        if id(traced) in seen:
            return self.missing(traced.name, ('sql-cycle', stmt.index, traced.name), stmt.ref)
        seen = seen | {id(traced)}
        expression = traced.expression
        if isinstance(expression, exp.Table):
            table_name = '.'.join(x.name for x in expression.parts)
            column_name = traced.name.split('.', 1)[-1]
            if '__QLIK_PARAMETER__' in table_name or '__QLIK_PARAMETER__' in column_name:
                return self.missing(traced.name, ('dynamic-source', stmt.index, traced.name), stmt.ref,
                                    note='源表名或列名来自运行时美元展开，静态导出无法确认。')
            return self.source(table_name, column_name, stmt.ref)
        if isinstance(expression, exp.Placeholder):
            return self.missing(traced.name, ('sql-unknown', stmt.index, traced.name), stmt.ref,
                                note='SQL 列无法唯一定位到源表；需要 schema 或修正字段限定符。')
        expr_sql = expression.sql(dialect='oracle', pretty=True)
        node = self.graph.add('sql', (stmt.index, traced.name, expr_sql),
                              f'{name}.{traced.name}', expression=expr_sql, ref=stmt.ref,
                              table=name, field=traced.name,
                              note='Oracle SQL AST 列级追溯；JOIN、WHERE 和聚合上下文见原始代码。')
        for downstream in traced.downstream:
            self.graph.link(self.sql_node(downstream, stmt, name, seen), node)
        if not traced.downstream and expression.find(exp.Column):
            self.graph.link(self.missing(traced.name, ('sql-leaf', stmt.index, traced.name), stmt.ref), node)
        return node

    def parse_load(self, stmt: Statement, name: str, preceding: Table | None = None) -> Table:
        s = stmt.clean
        columns_text, source_kind, rest = load_parts(stmt)
        source = preceding
        if source_kind != 'preceding':
            if source_kind == 'resident':
                resident = re.match(r'(\[[^\]]+\]|"[^"]+"|[\w.]+)', rest)
                resident_name = unquote(resident.group(1)) if resident else '?'
                source = self.tables.get(resident_name)
                if source is None:
                    self.warn('missing-resident', 'Resident 源表未找到：' + resident_name, stmt.ref)
            elif source_kind == 'inline':
                source = Table(name + ' · INLINE')
                inline = re.search(r'\[\s*([^\r\n]+)', rest)
                if inline:
                    for col in split_columns(inline.group(1).rstrip(']')):
                        col = unquote(col)
                        source.fields[col] = self.source(name + ' · INLINE', col, stmt.ref, source_type='inline')
            elif source_kind == 'from':
                file_match = re.match(r'(\[[^\]]+\]|\S+)', rest)
                file_name = unquote(file_match.group(1)) if file_match else '未知文件'
                source = Table(file_name)
                for item in split_columns(columns_text):
                    val = re.split(r'\s+AS\s+', item, flags=re.I)[0]
                    for col in tokens(val):
                        if col.upper() not in KEYWORDS and col not in self.variables:
                            source.fields[col] = self.source(file_name, col, stmt.ref, source_type='file')
                source.wildcards.append(dict(file=file_name, ref=stmt.ref))
            elif source_kind == 'autogenerate':
                source = Table('AUTOGENERATE')
        if source and source_kind in ('inline', 'from'):
            source.lineage_id = self.table_lineage.source(
                source.name, self.connection, 'inline' if source_kind == 'inline' else
                'unresolved' if '$(' in source.name else 'file', stmt.ref,
                field_nodes=source.fields)
        input_id = source.lineage_id if source else ''
        if not input_id and source_kind not in ('autogenerate',):
            input_id = self.table_lineage.source(
                resident_name if source_kind == 'resident' else '未确认的 LOAD 输入',
                '', 'unresolved', stmt.ref)
        table = Table(name)
        self.blocks.append(dict(kind='load', name=name, sourceKind=source_kind, ref=stmt.ref,
                                mapping=bool(re.search(r'\bMAPPING\b', s, re.I))))
        for item in split_columns(columns_text):
            if item == '*':
                if source:
                    for col, parent in source.fields.items():
                        node = self.graph.add('load', (stmt.index, name, col), f'{name}.{col}',
                                              expression=f'LOAD * → {col}', ref=stmt.ref,
                                              table=name, field=col, operation=source_kind)
                        self.graph.link(parent, node)
                        table.fields[col] = node
                    table.wildcards.extend(source.wildcards)
                else:
                    table.wildcards.append(dict(ref=stmt.ref))
                continue
            value, col = load_column(item)
            if value == item and not re.fullmatch(r'[\w .]+', col):
                self.warn('load-expression-name', '无 AS 的计算字段，其实际名称需运行时确认：' + col, stmt.ref)
            node = self.graph.add('load', (stmt.index, name, col), f'{name}.{col}',
                                  expression=item, ref=stmt.ref, table=name, field=col,
                                  operation=source_kind, confidence='review' if self.control_flow else 'parsed')
            if source_kind == 'autogenerate':
                self.bind(node, value, Table('generated'), allow_unknown=False)
                self.graph.nodes[node]['note'] = 'AUTOGENERATE 生成字段，无外部数据源。'
            else:
                self.bind(node, value, source or Table('missing'))
            table.fields[col] = node
        table = self.crosstable(table, stmt)
        operation = 'CROSSTABLE' if re.search(r'\bCROSSTABLE\s*\(', s, re.I) else source_kind.upper() + ' LOAD'
        self.table_lineage.stage(table, operation, stmt, [(input_id, ['data'])] if input_id else [],
                                 status='partial' if self.control_flow else 'complete')
        return table

    def crosstable(self, table: Table, stmt: Statement) -> Table:
        match = re.search(r'(?im)^\s*CROSSTABLE\s*\(([^)]*)\)', stmt.clean)
        if not match: return table
        args = split_columns(match.group(1))
        if len(args) not in (2, 3) or (len(args) == 3 and not args[2].isdigit()):
            self.warn('crosstable-arguments', 'Crosstable 参数无法静态确认，已标为待核实。', stmt.ref)
            for node in table.fields.values():
                self.graph.nodes[node]['confidence'] = 'review'
                self.graph.nodes[node]['note'] = 'Crosstable 参数无法静态确认。'
            return table
        attribute, value = map(unquote, args[:2])
        qualifiers = int(args[2]) if len(args) == 3 else 1
        columns = list(table.fields)
        pivoted = columns[qualifiers:]
        if not pivoted or qualifiers < 1 or table.wildcards:
            self.warn('crosstable-schema', 'Crosstable 输入列或限定列数量不完整；需补充加载字段清单。', stmt.ref)
        confidence = 'review' if self.control_flow or not pivoted or table.wildcards else 'parsed'
        result = Table(table.name, {col: table.fields[col] for col in columns[:qualifiers]})
        code = match.group().strip()
        attr_node = self.graph.add('load', ('crosstable', stmt.index, attribute), f'{table.name}.{attribute}',
                                  expression=f'{code}\n{attribute} ← 字段名：' + ', '.join(pivoted),
                                  ref=stmt.ref, table=table.name, field=attribute,
                                  operation='crosstable-attribute', confidence=confidence,
                                  note='属性值来自被转置列的字段名，不是这些列中的数值。', generated=True)
        value_node = self.graph.add('load', ('crosstable', stmt.index, value), f'{table.name}.{value}',
                                   expression=f'{code}\n{value} ← ' + ', '.join(pivoted),
                                   ref=stmt.ref, table=table.name, field=value,
                                   operation='crosstable-value', confidence=confidence,
                                   note=f'前 {qualifiers} 列保持为限定字段；后续 {len(pivoted)} 列转成该数值字段，保留全部列来源。')
        for col in pivoted: self.graph.link(table.fields[col], value_node)
        if not pivoted or table.wildcards:
            missing = self.missing(value, ('crosstable-schema', stmt.index), stmt.ref,
                                   note='Crosstable 输入列未完整导出，无法确认全部被转置字段。')
            self.graph.link(missing, value_node)
            self.graph.link(missing, attr_node)
        result.fields[attribute] = attr_node
        result.fields[value] = value_node
        return result

    def store(self, table: Table, command: str, stmt: Statement) -> None:
        # Qlik prefixes occur before the primary query. Never mistake a JOIN
        # inside an SQL subquery for a Qlik JOIN into the previous logical table.
        primary = re.search(r'(?im)^\s*(?:LOAD|(?:SQL\s+)?SELECT|WITH)\b', command)
        prefix = command[:primary.start()] if primary else ''
        concat = re.search(r'(?im)^\s*CONCATENATE\s*(?:\(\s*([^)]*?)\s*\))?', prefix)
        join = re.search(r'(?im)^\s*(?:(?:LEFT|RIGHT|INNER|OUTER)\s+)?JOIN\s*(?:\(\s*([^)]*?)\s*\))?\s*$', prefix)
        keep = re.search(r'(?im)^\s*(?:(LEFT|RIGHT|INNER)\s+)?KEEP\s*(?:\(\s*([^)]*?)\s*\))?\s*$', prefix)
        mapping = bool(re.search(r'\bMAPPING\b', prefix, re.I))
        keep_target = ''
        keep_source = ''
        if keep:
            keep_target = unquote(keep.group(2)) if keep.group(2) else self.last_table
            keep_source = self.tables[keep_target].lineage_id if keep_target in self.tables else ''
            if not keep_source:
                self.warn('missing-keep-target', 'KEEP 目标表未找到：' + keep_target, stmt.ref)
                keep_source = self.table_lineage.source(keep_target or '未确认的 KEEP 目标', '', 'unresolved', stmt.ref)
        target_name = ''
        if concat or join:
            mode = concat or join
            target_name = unquote(mode.group(1)) if mode and mode.group(1) else self.last_table
        elif not re.search(r'\b(NOCONCATENATE|KEEP|MAPPING)\b', prefix, re.I):
            for existing in self.tables.values():
                if table.fields and set(existing.fields) == set(table.fields) and not table.wildcards and not existing.wildcards:
                    target_name = existing.name
                    break
        if target_name and target_name in self.tables:
            target = self.tables[target_name]
            merged = dict(target.fields)
            for col, new in table.fields.items():
                if col in merged:
                    combined = self.graph.add('load', ('merge', stmt.index, target_name, col),
                                              f'{target_name}.{col}', expression='JOIN' if join else 'CONCATENATE',
                                              ref=stmt.ref, table=target_name, field=col,
                                              confidence='review' if join else 'parsed',
                                              note='JOIN 键及行数语义需核实。' if join else '合并多次加载的行来源。')
                    self.graph.link(merged[col], combined)
                    self.graph.link(new, combined)
                    merged[col] = combined
                else: merged[col] = new
            combined_table = Table(target_name, merged, target.wildcards + table.wildcards)
            join_type = re.search(r'\b(LEFT|RIGHT|INNER|OUTER)\s+JOIN\b', prefix, re.I)
            operation = ((join_type.group(1).upper() + ' ') if join_type else '') + 'JOIN' if join else 'CONCATENATE' if concat else 'AUTO CONCATENATE'
            self.table_lineage.version(combined_table, operation, stmt,
                [(target.lineage_id, ['data']), (table.lineage_id, ['data', 'context'] if join else ['data'])],
                previous=target.lineage_id, status='partial' if join else 'complete',
                note='JOIN 的关联键和行数语义需核实。' if join else '')
            self.tables[target_name] = combined_table
            self.last_table = target_name
        else:
            if target_name:
                self.warn('missing-merge-target', 'JOIN / CONCATENATE 目标表未找到：' + target_name, stmt.ref)
            if table.name in self.tables:
                # Qlik adds a suffix when the same label is reused with a different schema.
                table.name += f'-{stmt.index}'
                self.warn('repeated-table-label', '重复表标签已保留为独立加载块：' + table.name, stmt.ref)
            inputs = [(table.lineage_id, ['data'])]
            operation = 'MAPPING' if mapping else 'LOAD TABLE'
            status, note = ('partial', '映射查找依赖尚需核实。') if mapping else ('complete', '')
            if target_name:
                missing = self.table_lineage.source(target_name, '', 'unresolved', stmt.ref)
                inputs.append((missing, ['reference']))
                status = 'partial'
            if keep:
                side = (keep.group(1) or 'INNER').upper()
                operation, status, note = side + ' KEEP', 'partial', '保留两张表；关联键和行集效果需结合 Qlik 运行结果核实。'
                if side in ('LEFT', 'INNER'):
                    inputs.append((keep_source, ['context']))
                if side in ('RIGHT', 'INNER') and keep_target in self.tables:
                    target = self.tables[keep_target]
                    updated = Table(target.name, dict(target.fields), list(target.wildcards))
                    self.table_lineage.version(updated, operation, stmt,
                        [(keep_source, ['data']), (table.lineage_id, ['context'])],
                        previous=keep_source, status=status, note=note)
                    self.tables[keep_target] = updated
            self.table_lineage.version(table, operation, stmt, inputs,
                                       auxiliary=mapping, status=status, note=note)
            self.tables[table.name] = table
            self.last_table = table.name
        self.field_cache.clear()
