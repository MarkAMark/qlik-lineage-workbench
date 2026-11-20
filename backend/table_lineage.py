"""Table operations and versioned lineage, separate from column value dependencies."""
from __future__ import annotations

import re
from collections import defaultdict
from uuid import uuid4

from sqlglot import exp
from sqlglot.optimizer.scope import Scope

from .model import Graph, Table, key


class TableLineage:
    def __init__(self, graph: Graph, namespace: str = '') -> None:
        self.graph = graph
        self.namespace = key(namespace, uuid4().hex)
        self.nodes: dict[str, dict] = {}
        self.columns: dict[str, dict[str, str]] = {}
        self.operations: dict[str, dict] = {}
        self.links: list[dict] = []
        self.instances: dict[str, list[str]] = defaultdict(list)
        self.datasets: dict[str, dict] = {}
        self.bindings: dict[str, dict] = {}
        self.usages: dict[str, dict] = {}
        self.warnings: list[dict] = []
        self.script = ''
        self.app_name = ''
        self._ancestors: dict[str, set[str]] = {}
        self._projection: dict[str, dict] | None = None

    def source(self, name: str, connection: str, source_type: str, ref: dict,
               columns=(), field_nodes: dict[str, str] | None = None) -> str:
        identity = (name, ref.get('file'), ref.get('line'), ref.get('endLine')) if source_type == 'unresolved' else name
        node_id = 'table-source:' + key(self.namespace, source_type, connection, identity)
        if node_id not in self.nodes:
            unresolved = source_type == 'unresolved'
            self.nodes[node_id] = dict(
                id=node_id, kind='table_unresolved' if unresolved else 'table_source',
                label=name, table=name, connection=connection, sourceType=source_type,
                status='unresolved' if unresolved else 'partial' if source_type == 'database' and not connection else 'complete',
                confidence='unresolved' if unresolved else 'review' if source_type == 'database' and not connection else 'parsed',
                ref=ref, refs=[ref], instanceId=node_id, version=0, current=True,
                dropped=False, auxiliary=False, schemaStatus='unknown',
                note='来源身份待确认。' if unresolved else '连接身份未导出。' if source_type == 'database' and not connection else '',
            )
            self.columns[node_id] = {}
        node = self.nodes[node_id]
        if ref not in node['refs']:
            node['refs'].append(ref)
        for column in columns:
            self.columns[node_id].setdefault(column, '')
        for column, field_node in (field_nodes or {}).items():
            self.columns[node_id][column] = field_node
        return node_id

    def _operation(self, kind: str, stmt, note: str = '') -> str:
        op_id = 'table-operation:' + key(self.namespace, len(self.operations), stmt.index, kind)
        self.operations[op_id] = dict(id=op_id, kind=kind, ref=stmt.ref, note=note)
        return op_id

    def _connect(self, inputs: list[tuple[str, list[str]]], target: str, op_id: str) -> None:
        for source, roles in inputs:
            if source and source in self.nodes:
                self.links.append(dict(source=source, target=target, roles=sorted(set(roles)), operation=op_id))
        self._projection = None

    def stage(self, table: Table, kind: str, stmt, inputs: list[tuple[str, list[str]]],
              *, status: str = 'complete', note: str = '') -> None:
        op_id = self._operation(kind, stmt, note)
        node_id = 'table-stage:' + key(op_id)
        self.nodes[node_id] = dict(id=node_id, kind='table_stage', label=table.name,
                                   table=table.name, status=status, ref=stmt.ref, operation=op_id,
                                   confidence='parsed' if status == 'complete' else 'review', note=note)
        self.columns[node_id] = dict(table.fields)
        self._connect(inputs, node_id, op_id)
        table.lineage_id = node_id

    def version(self, table: Table, kind: str, stmt, inputs: list[tuple[str, list[str]]],
                *, previous: str = '', auxiliary: bool = False, status: str = 'complete', note: str = '') -> str:
        op_id = self._operation(kind, stmt, note)
        instance = self.nodes[previous]['instanceId'] if previous else 'table-instance:' + key(self.namespace, op_id)
        number = len(self.instances[instance]) + 1
        node_id = 'table-version:' + key(instance, number)
        if previous:
            self.nodes[previous]['current'] = False
        self.nodes[node_id] = dict(
            id=node_id, kind='table_mapping' if auxiliary else 'table', label=table.name, table=table.name,
            instanceId=instance, version=number, current=True, dropped=False, auxiliary=auxiliary,
            status=status, confidence='parsed' if status == 'complete' else 'review', ref=stmt.ref,
            refs=[stmt.ref], operation=op_id, note=note, connection='', sourceType='logical',
            schemaStatus=('partial' if table.fields else 'unknown') if table.wildcards else 'known',
        )
        self.columns[node_id] = dict(table.fields)
        self.instances[instance].append(node_id)
        self._connect(inputs, node_id, op_id)
        table.lineage_id = node_id
        return node_id

    def drop(self, table: Table, stmt) -> None:
        if table.lineage_id not in self.nodes:
            return
        instance = self.nodes[table.lineage_id]['instanceId']
        for version in self.instances[instance]:
            self.nodes[version]['dropped'] = True
            self.nodes[version]['dropRef'] = stmt.ref
            self.nodes[version]['current'] = False
        self._operation('DROP TABLE', stmt)

    def sql_inputs(self, scope: Scope, table: Table, connection: str, stmt) -> list[tuple[str, list[str]]]:
        """Follow used scopes, retaining row-only reads without promoting them to column edges."""
        value_sources = set()
        for field_node in table.fields.values():
            value_sources.update(
                (n.get('connection', ''), n.get('table', '')) for n in
                (self.graph.nodes[i] for i in self.graph.ancestors(field_node)) if n['kind'] == 'source'
            )
        pending, seen, inputs = [scope], set(), {}
        while pending:
            nested = pending.pop()
            if id(nested) in seen:
                continue
            seen.add(id(nested))
            pending.extend(nested.subquery_scopes)
            pending.extend(nested.union_scopes)
            predicate_scope = False
            parent = nested.expression.parent
            while parent is not None:
                if isinstance(parent, (exp.Where, exp.Having, exp.Exists, exp.In)):
                    predicate_scope = True
                    break
                if isinstance(parent, exp.Query):
                    break
                parent = parent.parent
            for alias, (reference, source) in nested.selected_sources.items():
                if isinstance(source, Scope):
                    pending.append(source)
                    continue
                if not isinstance(source, exp.Table):
                    continue
                name = '.'.join(part.name for part in source.parts)
                dynamic = '__QLIK_PARAMETER__' in name
                if dynamic:
                    name = f'动态 SQL 来源（{alias}，需运行时展开）'
                columns = {c.name for c in nested.columns if c.table == alias and not c.is_star}
                source_id = self.source(name, connection, 'unresolved' if dynamic else 'database', stmt.ref, columns)
                roles = inputs.setdefault(source_id, set())
                is_join = isinstance(reference.parent, exp.Join)
                if (connection, name) in value_sources:
                    roles.add('data')
                elif not predicate_scope and not is_join:
                    roles.add('data')  # COUNT(*), SELECT 1 and unknown schemas still read a row set.
                if predicate_scope or is_join:
                    roles.add('context')
                for column in nested.columns:
                    if column.table != alias:
                        continue
                    ancestor = column.parent
                    while ancestor is not None and ancestor is not nested.expression:
                        if isinstance(ancestor, (exp.Where, exp.Having, exp.Join)):
                            roles.add('context')
                            break
                        ancestor = ancestor.parent
                if not roles:
                    roles.add('reference')
        return [(source, sorted(roles)) for source, roles in inputs.items()]

    @staticmethod
    def _roles(left: list[str], right: list[str]) -> list[str]:
        result = set()
        if 'data' in left and 'data' in right:
            result.add('data')
        if 'context' in left or 'context' in right:
            result.add('context')
        if 'reference' in left or 'reference' in right:
            result.add('reference')
        return sorted(result or {'reference'})

    def project(self) -> dict[str, dict]:
        if self._projection is not None:
            return self._projection
        incoming = defaultdict(list)
        for edge in self.links:
            incoming[edge['target']].append(edge)
        edges = {}
        for target, node in self.nodes.items():
            if node['kind'] not in ('table', 'table_mapping'):
                continue
            pending = [(e['source'], e['roles'], [e['operation']], frozenset()) for e in incoming[target]]
            while pending:
                source, roles, operations, visited = pending.pop()
                if source in visited:
                    continue
                if self.nodes[source]['kind'] == 'table_stage':
                    for edge in incoming[source]:
                        pending.append((edge['source'], self._roles(edge['roles'], roles),
                                        [edge['operation'], *operations], visited | {source}))
                    continue
                edge_id = 'table-edge:' + key(source, target)
                item = edges.setdefault(edge_id, dict(id=edge_id, source=source, target=target,
                                                       roles=[], operationIds=[], relation='table'))
                item['roles'] = sorted(set(item['roles']) | set(roles))
                item['operationIds'] = list(dict.fromkeys([*item['operationIds'], *operations]))
        for edge in edges.values():
            edge['operationKinds'] = list(dict.fromkeys(self.operations[i]['kind'] for i in edge['operationIds']))
            statuses = {self.nodes[i]['status'] for i in (edge['source'], edge['target'])}
            edge['status'] = 'unresolved' if 'unresolved' in statuses else 'partial' if 'partial' in statuses else 'complete'
        self._projection = edges
        return edges

    def ancestors(self, field_node: str) -> set[str]:
        if field_node not in self._ancestors:
            self._ancestors[field_node] = self.graph.ancestors(field_node)
        return self._ancestors[field_node]

    def finalize(self, live: dict[str, Table], usages: dict[str, dict], warnings: list[dict], app_name: str) -> None:
        self.usages, self.warnings, self.app_name = usages, warnings, app_name
        uncertain = any(w['code'] in ('unsupported-script', 'control-flow', 'missing-include', 'missing-merge-target',
                                     'missing-keep-target', 'missing-preceding-source') for w in warnings)
        for node in self.nodes.values():
            if node['kind'] in ('table', 'table_mapping') and uncertain:
                node['status'], node['confidence'] = 'partial', 'review'
                node['note'] = (node.get('note', '') + ' App 含未确认的脚本或模型状态，表关系为已导出定义内的静态结果。').strip()
        for graph_node in self.graph.nodes.values():
            if graph_node['kind'] == 'source':
                source_type = 'unresolved' if '$(' in graph_node['table'] else graph_node.get('sourceType', 'database')
                self.source(graph_node['table'], graph_node.get('connection', ''), source_type,
                            graph_node.get('ref') or {}, field_nodes={graph_node['field']: graph_node['id']})
        for usage_id, usage in usages.items():
            ref = self.graph.nodes[usage_id].get('ref') or {}
            pointer = re.split(r'/qHyperCubeDef|/qListObjectDef', ref.get('pointer', ''))[0]
            dataset_id = 'chart-dataset:' + key(self.namespace, usage['sheetId'], usage['chartId'], ref.get('file'), pointer)
            dataset = self.datasets.setdefault(dataset_id, dict(
                id=dataset_id, kind='dataset', label=usage['chartTitle'], table=usage['chartTitle'],
                sheetId=usage['sheetId'], sheetTitle=usage['sheetTitle'], chartId=usage['chartId'],
                status='complete', confidence='parsed', fieldIds=[], ref=ref, current=True,
                instanceId=dataset_id, version=0, dropped=False, auxiliary=False,
                sourceType='visualization', connection='', schemaStatus='known',
                note='图表逻辑数据集：展示字段定义的容器；不代表已创建或物化数据表。',
            ))
            dataset['fieldIds'].append(usage_id)
            refs, unknown, ambiguous, pending, visited = [], [], False, [usage_id], set()
            while pending:
                node_id = pending.pop()
                if node_id in visited:
                    continue
                visited.add(node_id)
                node = self.graph.nodes[node_id]
                if node['kind'] == 'field':
                    names = node.get('tables', [])
                    ambiguous = ambiguous or len(names) > 1
                    for name in names:
                        table = live.get(name)
                        column = node.get('field', node['label'])
                        if table and table.lineage_id and column in table.fields:
                            refs.append(dict(version=table.lineage_id, field=column, node=table.fields[column]))
                    continue
                if node['confidence'] == 'unresolved':
                    unknown.append(node_id)
                pending.extend(self.graph.incoming.get(node_id, ()))
            refs = list({(r['version'], r['field']): r for r in refs}.values())
            self.bindings[usage_id] = dict(datasetId=dataset_id, tableRefs=refs,
                tableIds=sorted({r['version'] for r in refs}), unresolved=unknown,
                mappingStatus='unresolved' if unknown and not refs else 'review' if ambiguous or unknown else 'multiple' if len({r['version'] for r in refs}) > 1 else 'resolved' if refs else 'no_table')
        self._projection = None

    def public_node(self, node_id: str) -> dict:
        node = self.nodes.get(node_id) or self.datasets[node_id]
        fields = self.columns.get(node_id, {})
        total_versions = len(self.instances.get(node['instanceId'], []))
        return dict(node, fieldNames=sorted(fields), fieldCount=len(fields), versionCount=total_versions,
                    lifecycle='source' if node['kind'].startswith('table_source') else 'unresolved' if node['kind'] == 'table_unresolved' else 'dataset' if node['kind'] == 'dataset' else 'final' if node['current'] else 'intermediate')

    def _table_ancestors(self, seeds: set[str], include_context: bool = True) -> set[str]:
        incoming = defaultdict(list)
        for edge in self.project().values():
            if include_context or 'data' in edge['roles']:
                incoming[edge['target']].append(edge['source'])
        result, pending = set(seeds), list(seeds)
        while pending:
            for source in incoming[pending.pop()]:
                if source not in result:
                    result.add(source)
                    pending.append(source)
        return result

    def view(self, *, scope: str = 'app', usage: str = '', sheet: str = '', chart: str = '',
             version: str = '', field: str = '', include_context: bool = True) -> dict:
        if scope not in ('app', 'sheet', 'chart', 'field'):
            raise ValueError('无效的表血缘范围。')
        base_ids = {i for i, n in self.nodes.items() if n['kind'] != 'table_stage'}
        selected_usages = []
        if scope == 'field' and version:
            if version not in self.columns or field not in self.columns[version]:
                raise KeyError('表版本或字段')
            ids = self._table_ancestors({version}, include_context)
        elif scope == 'app':
            ids = base_ids
        else:
            if scope == 'field' and usage not in self.bindings:
                raise KeyError('字段使用处')
            if scope in ('sheet', 'chart') and not sheet:
                raise ValueError('需要选择 Sheet。')
            if scope == 'chart' and not chart:
                raise ValueError('需要选择图表。')
            selected_usages = [i for i, f in self.usages.items() if
                               (scope == 'field' and i == usage) or
                               (scope == 'sheet' and f['sheetId'] == sheet) or
                               (scope == 'chart' and f['sheetId'] == sheet and f['chartId'] == chart)]
            seeds = {v for i in selected_usages for v in self.bindings[i]['tableIds']}
            ids = self._table_ancestors(seeds, include_context)
        edges = [dict(e) for e in self.project().values() if e['source'] in ids and e['target'] in ids
                 and (include_context or 'data' in e['roles'])]
        nodes = [self.public_node(i) for i in self.nodes if i in ids]
        grouped = defaultdict(list)
        for usage_id in selected_usages:
            grouped[self.bindings[usage_id]['datasetId']].append(usage_id)
        for dataset_id, usage_ids in grouped.items():
            dataset = self.public_node(dataset_id)
            dataset['fieldIds'] = usage_ids
            dataset['fieldCount'] = len(usage_ids)
            dataset['focusLabel'] = self.usages[usage_ids[0]]['label'] if scope == 'field' else ''
            dataset['status'] = 'partial' if any(self.bindings[u]['mappingStatus'] in ('review', 'unresolved') for u in usage_ids) else 'complete'
            dataset['confidence'] = 'review' if dataset['status'] == 'partial' else 'parsed'
            nodes.append(dataset)
            for table_id in sorted({v for u in usage_ids for v in self.bindings[u]['tableIds']}):
                field_ids = [u for u in usage_ids if table_id in self.bindings[u]['tableIds']]
                edges.append(dict(id='consumption:' + key(table_id, dataset_id), source=table_id, target=dataset_id,
                    relation='consumption', roles=['consumption'], operationIds=[], operationKinds=['图表消费'],
                    status=dataset['status'], usageIds=field_ids))
        instances = {self.nodes[i]['instanceId'] for i in ids if self.nodes[i]['kind'] in ('table', 'table_mapping')}
        final = {self.nodes[i]['instanceId'] for i in ids if self.nodes[i]['kind'] == 'table' and self.nodes[i]['current']}
        stats = dict(sourceAssets=sum(self.nodes[i]['kind'] == 'table_source' for i in ids), finalTables=len(final),
                     intermediateTables=len(instances - final), versions=sum(self.nodes[i]['kind'] in ('table', 'table_mapping') for i in ids),
                     relations=len(edges), datasets=len(grouped), review=sum(n['status'] != 'complete' for n in nodes))
        return dict(nodes=nodes, edges=edges, scope=scope, root=version or usage, stats=stats,
                    totalTables=len(base_ids), appName=self.app_name, boundaries=self.warnings,
                    bindings={i: self.bindings[i] for i in selected_usages},
                    scopeNote='展示当前字段所涉及表的完整加载路径；其他列来源和行集作用属于表级上下文。' if scope == 'field' else
                              '按已识别的图表字段依赖筛选；运行时 Qlik 关联仍需核实。' if scope != 'app' else '当前 App 已导出脚本中的表依赖；图表逻辑数据集按需展示。')

    def consumers(self, node_id: str) -> list[dict]:
        result = []
        for usage_id, binding in self.bindings.items():
            if node_id not in self._table_ancestors(set(binding['tableIds'])):
                continue
            column_ancestors = self.ancestors(usage_id)
            value = any(n and n in column_ancestors for n in self.columns.get(node_id, {}).values())
            result.append(dict(**self.usages[usage_id], influence='value' if value else 'context'))
        return result

    def original(self, ref: dict | None) -> str:
        if not ref or ref.get('file') != 'script.qvs':
            return ''
        return '\n'.join(self.script.splitlines()[ref['line'] - 1:ref['endLine']])

    def operation_details(self, ids: list[str]) -> list[dict]:
        # A materialization and its SQL can share a statement; show its code once.
        result = {}
        for op_id in ids:
            operation = self.operations[op_id]
            ref = operation['ref']
            identity = (ref['file'], ref['line'], ref['endLine'])
            item = result.setdefault(identity, dict(id=op_id, kinds=[], ref=ref, code=self.original(ref), notes=[]))
            if operation['kind'] not in item['kinds']:
                item['kinds'].append(operation['kind'])
            if operation['note'] and operation['note'] not in item['notes']:
                item['notes'].append(operation['note'])
        return list(result.values())

    def detail(self, node_id: str, *, offset: int = 0, limit: int = 200, query: str = '') -> dict:
        node = self.public_node(node_id)
        if node['kind'] == 'dataset':
            return dict(node=node, fields=[], fieldTotal=0, versions=[], operations=[],
                        consumers=[dict(**self.usages[i], influence='value') for i in self.datasets[node_id]['fieldIds']])
        columns = [(name, field_node) for name, field_node in self.columns[node_id].items() if query.casefold() in name.casefold()]
        columns.sort()
        op_ids = [self.nodes[node_id]['operation']] if self.nodes[node_id].get('operation') else []
        op_ids += [op for edge in self.project().values() if edge['target'] == node_id for op in edge['operationIds']]
        if node['kind'] in ('table_source', 'table_unresolved'):
            op_ids += [op for edge in self.project().values() if edge['source'] == node_id for op in edge['operationIds']]
        return dict(node=node, fields=[dict(name=name, nodeId=field_node or None,
                    status='complete' if field_node else 'partial') for name, field_node in columns[offset:offset + limit]],
                    fieldTotal=len(columns), offset=offset, limit=limit,
                    versions=[self.public_node(i) for i in self.instances.get(node['instanceId'], [])],
                    operations=self.operation_details(list(dict.fromkeys(op_ids))), consumers=self.consumers(node_id))

    def evidence(self, edge_id: str, *, offset: int = 0, limit: int = 200) -> dict:
        edge = self.project()[edge_id]
        pairs = []
        if 'data' in edge['roles']:
            for target_name, target_node in self.columns[edge['target']].items():
                if not target_node:
                    continue
                ancestors = self.ancestors(target_node)
                for source_name, source_node in self.columns[edge['source']].items():
                    if source_node and source_node in ancestors:
                        pairs.append(dict(sourceField=source_name, targetField=target_name, targetNode=target_node,
                                          sourceNode=source_node, targetVersion=edge['target']))
        return dict(edge=edge, source=self.public_node(edge['source']), target=self.public_node(edge['target']),
                    operations=self.operation_details(edge['operationIds']), fieldMappings=pairs[offset:offset + limit],
                    mappingTotal=len(pairs), offset=offset, limit=limit,
                    note='字段映射仅列出已确认的计算依赖；过滤、行集或未知 schema 可以没有数值映射。')

    def field_trace(self, version: str, field: str) -> dict:
        if version not in self.columns or field not in self.columns[version]:
            raise KeyError('表版本或字段')
        field_node = self.columns[version][field]
        if field_node:
            trace = self.graph.trace(field_node)
        else:
            missing_id = 'technical-gap:' + key(version, field)
            missing = dict(id=missing_id, kind='unresolved', label=field, table=self.nodes[version]['label'], field=field,
                           confidence='unresolved', ref=self.nodes[version]['ref'],
                           note='已识别引用列，但未建立可靠的字段计算映射；表级关系和原始代码仍可查看。')
            trace = dict(root=missing_id, nodes=[missing], edges=[], status='unresolved',
                         sourceCount=0, unresolvedCount=1, reviewCount=0,
                         rootEvidence=dict(**missing, expression=field, original=self.original(missing['ref']),
                                           inputs=[], consumers=[], upstream=0, downstream=0))
        context = [dict(id=e['id'], source=self.nodes[e['source']]['label'], roles=e['roles'],
                        operationKinds=e['operationKinds']) for e in self.project().values() if e['target'] == version]
        return dict(**trace, technicalField=dict(version=version, field=field, nodeId=field_node or None,
                                                table=self.nodes[version]['label']), tableContext=context,
                    appName=self.app_name, boundaries=self.warnings)
