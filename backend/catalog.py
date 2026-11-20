from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from .assessment import estimate, risk
from .model import Graph, key
from .script import ScriptParser, expression_refs, tokens
from .source_file import json_locations


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else: result[k] = copy.deepcopy(v)
    return result


def pointer_part(value: str) -> str:
    return value.replace('~', '~0').replace('/', '~1')


def friendly_label(label: str, expression: str) -> str:
    if label and not label.lstrip().startswith('='):
        return label
    basic = re.fullmatch(r'\s*(AVG|SUM|COUNT|MAX|MIN)\(\s*([\w.]+)\s*\)\s*', expression, re.I)
    if basic:
        return basic.group(2) + ' · ' + {'avg': '平均值', 'sum': '合计', 'count': '计数', 'max': '最大值', 'min': '最小值'}[basic.group(1).lower()]
    return re.sub(r'\s+', ' ', expression).strip()[:90] or label or '未导出表达式'


def stream_info(props: dict, fallback: str = '') -> dict:
    value = props.get('stream') or props.get('qStream') or (props.get('qMetaDef') or {}).get('stream')
    if isinstance(value, dict):
        name = str(value.get('name') or value.get('qName') or '')
        identifier = str(value.get('id') or value.get('qId') or '')
        if name or identifier:
            return dict(id='stream:' + key(identifier or name), name=name or identifier, source='metadata')
    elif isinstance(value, str) and value.strip():
        return dict(id='stream:' + key(value.strip()), name=value.strip(), source='metadata')
    return dict(id='stream:' + key(fallback) if fallback else 'stream:unknown',
                name=fallback or '未标注 Stream', source='directory' if fallback else 'unknown')


class Application:
    def __init__(self, path: Path, *, identity: str = '', stream_name: str = '', folder: str = '') -> None:
        self.path = path
        self.id = key(identity or path.name)
        self.folder = folder or path.name
        self.name = path.name
        self.graph = Graph()
        self.files: dict[str, str] = {}
        self.documents: dict[str, object] = {}
        self.source_locations: dict[str, dict] = {}
        self.variables: dict[str, str] = {}
        self.fields: dict[str, dict] = {}
        self.sheets: list[dict] = []
        self.extensions: Counter = Counter()
        self.charts: list[dict] = []
        self.objects: dict[str, tuple[dict, str]] = {}
        self.master_nodes: dict[tuple[str, str], str] = {}
        self.master_defs: dict[tuple[str, str], tuple[dict, str, int]] = {}
        self.master_titles: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.metadata_warnings: list[dict] = []
        self.parse_errors: list[str] = []
        props = self.read_json('app-properties.json', {})
        self.stream = stream_info(props, stream_name)
        self.name = props.get('qTitle', path.name)
        self.last_reload = props.get('qLastReloadTime', '')
        for i, variable in enumerate(self.read_json('variables.json', [])):
            name = variable.get('qName', variable.get('qInfo', {}).get('qId', ''))
            if not name: continue
            self.variables[name] = self.graph.add('variable', name, name,
                                                 expression=str(variable.get('qDefinition', '')),
                                                 ref=dict(file='variables.json', pointer=f'/{i}'),
                                                 note='导出的变量定义 / 当前值；不执行美元展开。')
        for kind, filename in [('dimension', 'dimensions.json'), ('measure', 'measures.json')]:
            for i, definition in enumerate(self.read_json(filename, [])):
                master_id = definition.get('qInfo', {}).get('qId', '')
                self.master_defs[(kind, master_id)] = (definition, filename, i)
                title = definition.get('qMetaDef', {}).get('title', '')
                if title: self.master_titles[title].append((kind, master_id))
        script_path = path / 'script.qvs'
        script = script_path.read_text(encoding='utf-8-sig') if script_path.is_file() else ''
        self.files['script.qvs'] = script
        self.parser = ScriptParser(self.graph, self.variables, self.id)
        self.parser.parse(script)
        if not script:
            self.parser.warn('missing-script', '未导出加载脚本，字段到数据源的血缘无法确认。')
        # Bind variable definitions after the final model is known.
        for name, node in self.variables.items():
            expression = self.graph.nodes[node]['expression']
            self.parser.bind(node, expression, allow_unknown=bool(re.search(r'[($=+*/<>]', expression)))
        self.mark_variable_cycles()
        objects_dir = path / 'objects'
        for filename in sorted(objects_dir.glob('*.json')):
            relative = filename.relative_to(path).as_posix()
            doc = self.read_json(relative, {})
            prop = doc.get('qProperty', doc)
            object_id = prop.get('qInfo', {}).get('qId')
            if object_id: self.objects[object_id] = (doc, relative)
        for object_id, (doc, filename) in self.objects.items():
            prop = doc.get('qProperty', doc)
            if prop.get('qInfo', {}).get('qType') != 'sheet': continue
            try:
                sheet_rank = float(prop.get('rank', 0))
                if not math.isfinite(sheet_rank): raise ValueError('non-finite rank')
            except (ValueError, TypeError):
                sheet_rank = 0
                self.metadata_warnings.append(dict(code='invalid-sheet-rank',
                    message='Sheet 排序值无法识别，已使用默认顺序：' + object_id))
            sheet = dict(id=object_id, title=prop.get('qMetaDef', {}).get('title') or prop.get('title') or object_id,
                         rank=sheet_rank, fields=[], chartCount=0,
                         ref=dict(file=filename, pointer='/qProperty'))
            self.sheets.append(sheet)
            for i, child in enumerate(doc.get('qChildren', [])):
                self.walk_object(child, filename, f'/qChildren/{i}', sheet, set())
            sheet['chartCount'] = sum(c['sheetId'] == object_id for c in self.charts)
        self.sheets.sort(key=lambda s: (s['rank'], s['title']))
        self.mark_expression_cycles()
        for field in self.fields.values():
            trace = self.graph.trace(field['id'])
            field['status'] = trace['status']
            field['sourceCount'] = trace['sourceCount']
            code = [self.graph.nodes[n]['expression'] for n in self.graph.ancestors(field['id'])
                    if self.graph.nodes[n]['kind'] in ('usage', 'expression', 'master', 'variable')]
            field['risk'] = risk('\n'.join(code))
        for sheet in self.sheets:
            sheet['fieldCount'] = len(sheet['fields'])
        self.warnings = self.parser.warnings + self.metadata_warnings
        self.stats = self.summary_stats()
        self.table_lineage = self.parser.table_lineage
        self.table_lineage.finalize(self.parser.tables, self.fields, self.warnings, self.name)

    def read_json(self, filename: str, default):
        file = self.path / filename
        if not file.is_file():
            self.metadata_warnings.append(dict(code='missing-file', message='缺少元数据文件：' + filename))
            return default
        try:
            raw = file.read_text(encoding='utf-8-sig')
            result = json.loads(raw)
            self.files[filename] = raw
            self.documents[filename] = result
            return result
        except (ValueError, OSError) as error:
            self.metadata_warnings.append(dict(code='invalid-json', message=filename + '：' + str(error)))
            return default

    def mark_variable_cycles(self) -> None:
        remaining = set(self.variables.values())
        while True:
            removable = {n for n in remaining if not (self.graph.incoming.get(n, set()) & remaining)}
            if not removable: break
            remaining -= removable
        for node in remaining:
            self.graph.nodes[node]['confidence'] = 'review'
            self.graph.nodes[node]['note'] = '变量存在循环依赖或依赖循环变量；需要人工核实。'
        if remaining:
            self.parser.warn('variable-cycle', '发现循环变量依赖，已标为待核实。')

    def expand_for_risk(self, expression: str, visited: set[str] | None = None) -> str:
        visited = set() if visited is None else visited
        pieces = [expression]
        for token in tokens(expression):
            if token in self.variables and token not in visited:
                visited.add(token)
                pieces.append(self.expand_for_risk(self.graph.nodes[self.variables[token]]['expression'], visited))
        return '\n'.join(pieces)

    def mark_expression_cycles(self) -> None:
        indegree = {n: len(self.graph.incoming.get(n, ())) for n in self.graph.nodes}
        queue = [n for n, degree in indegree.items() if not degree]
        for node in queue:
            for child in self.graph.outgoing.get(node, ()):
                indegree[child] -= 1
                if not indegree[child]: queue.append(child)
        remaining = {n for n, degree in indegree.items() if degree}
        for node in remaining:
            if self.graph.nodes[node]['confidence'] != 'unresolved':
                self.graph.nodes[node]['confidence'] = 'review'
                self.graph.nodes[node]['note'] = '存在循环表达式引用或依赖循环节点；需要人工核实。'
        if remaining: self.parser.warn('expression-cycle', '发现循环表达式引用，相关血缘已标为待核实。')

    def named_master_refs(self, expression: str, exclude: str = '') -> dict[str, str]:
        result = {}
        known = {f for table in self.parser.tables.values() for f in table.fields}
        for name, kind in expression_refs(expression):
            candidates = self.master_titles.get(name, [])
            if kind != 'variable' and name not in known and name not in self.variables and len(candidates) == 1:
                node = self.master(*candidates[0])[0]
                if node != exclude: result[name] = node
        return result

    def master(self, kind: str, master_id: str) -> tuple[str, str, str]:
        identity = (kind, master_id)
        if identity in self.master_nodes:
            node = self.master_nodes[identity]
            return node, self.graph.nodes[node]['expression'], self.graph.nodes[node]['label']
        if identity not in self.master_defs:
            missing = self.parser.missing(master_id, ('master', kind, master_id), note='主项 ID 存在，但定义未导出。')
            self.master_nodes[identity] = missing
            return missing, '', master_id
        definition, filename, index = self.master_defs[identity]
        if kind == 'measure':
            expressions = [definition.get('qMeasure', {}).get('qDef', '')]
        else:
            expressions = definition.get('qDim', {}).get('qFieldDefs', [])
        expression = '\n'.join(expressions)
        title = definition.get('qMetaDef', {}).get('title', master_id)
        node = self.graph.add('master', identity, friendly_label(title, expression),
                              expression=expression, masterId=master_id,
                              ref=dict(file=filename, pointer=f'/{index}'))
        self.master_nodes[identity] = node
        self.parser.bind(node, expression, references=self.named_master_refs(expression, exclude=node))
        if self.graph.nodes[node]['confidence'] == 'review' and '自引用' in self.graph.nodes[node].get('note', ''):
            self.parser.warn('expression-cycle', '主项存在自引用：' + title)
        return node, expression, title

    def walk_object(self, obj: dict, filename: str, pointer: str, sheet: dict, seen: set[str]) -> None:
        original_prop = obj.get('qProperty', obj)
        prop = original_prop
        children = obj.get('qChildren', [])
        prop_file, prop_pointer = filename, pointer + ('/qProperty' if 'qProperty' in obj else '')
        child_file, child_pointer = filename, pointer
        extends = prop.get('qExtendsId', '')
        if extends:
            if extends in seen:
                self.metadata_warnings.append(dict(code='master-object-cycle', message='主可视化循环引用：' + extends))
                return
            if extends in self.objects:
                base, base_file = self.objects[extends]
                base_prop = base.get('qProperty', base)
                prop = deep_merge(base_prop, original_prop)
                if not any(k in original_prop for k in ('qHyperCubeDef', 'qListObjectDef')):
                    prop_file, prop_pointer = base_file, '/qProperty' if 'qProperty' in base else ''
                if not children:
                    children = base.get('qChildren', [])
                    child_file, child_pointer = base_file, ''
            else:
                self.metadata_warnings.append(dict(code='missing-master-object', message='主可视化未导出：' + extends))
        chart_id = original_prop.get('qInfo', {}).get('qId', key(filename, pointer))
        chart_type = prop.get('visualization', prop.get('qInfo', {}).get('qType', 'unknown'))
        chart_title = prop.get('title') or prop.get('qMetaDef', {}).get('title') or chart_type
        if not isinstance(chart_title, str): chart_title = chart_type
        if chart_title.lstrip().startswith('='): chart_title = chart_type + ' · 动态标题'
        cube = prop.get('qHyperCubeDef', {})
        field_sources = [('dimension', cube.get('qDimensions', []), '/qHyperCubeDef/qDimensions'),
                         ('measure', cube.get('qMeasures', []), '/qHyperCubeDef/qMeasures')]
        if prop.get('qListObjectDef'):
            field_sources.append(('filter', [prop['qListObjectDef']], '/qListObjectDef'))
        has_fields = any(items for _, items, _ in field_sources)
        if has_fields or chart_type not in ('filterpane', 'listbox'):
            self.charts.append(dict(id=chart_id, title=chart_title, type=chart_type, sheetId=sheet['id']))
            if prop.get('extensionMeta', {}).get('isThirdParty') or chart_type in ('SimpleFieldSelect', 'qlik-variable-input', 'qlik-button-for-navigation', 'action-button'):
                self.extensions[chart_type] += 1
        pending_bindings = []
        for kind, items, suffix in field_sources:
            for i, item in enumerate(items):
                qdef = item.get('qDef', {})
                if isinstance(qdef, str): qdef = {'qDef': qdef}
                master_id = item.get('qLibraryId', '')
                if master_id:
                    parent, expression, original_label = self.master('dimension' if kind != 'measure' else kind, master_id)
                    self.add_usage(sheet, chart_id, chart_title, chart_type, kind, i, 0,
                                   expression, original_label, parent,
                                   dict(file=prop_file, pointer=prop_pointer + suffix + (f'/{i}' if kind != 'filter' else '')),
                                   master_id)
                else:
                    expressions = [qdef.get('qDef', '')] if kind == 'measure' else qdef.get('qFieldDefs', [])
                    labels = qdef.get('qFieldLabels', [])
                    for j, expression in enumerate(expressions):
                        if not isinstance(expression, str) or not expression.strip(): continue
                        original_label = qdef.get('qLabel', '') if kind == 'measure' else (labels[j] if j < len(labels) else '')
                        ref = dict(file=prop_file, pointer=prop_pointer + suffix + (f'/{i}' if kind != 'filter' else ''))
                        simple = expression.strip().strip('[]')
                        if kind != 'measure' and re.fullmatch(r'[\w .]+', simple) and not expression.startswith('='):
                            parent = self.parser.resolve(simple)
                        else:
                            parent = self.graph.add('expression', (sheet['id'], chart_id, kind, i, j),
                                                    friendly_label('', expression), expression=expression, ref=ref)
                            pending_bindings.append((parent, expression))
                        self.add_usage(sheet, chart_id, chart_title, chart_type, kind, i, j,
                                       expression, original_label, parent, ref, '')
        labels = defaultdict(list)
        for field in self.fields.values():
            if field['sheetId'] == sheet['id'] and field['chartId'] == chart_id:
                label = field['originalLabel']
                if label and not label.lstrip().startswith('='):
                    labels[label].extend(self.graph.incoming[field['id']])
        local_refs = {label: parents[0] for label, parents in labels.items() if len(parents) == 1}
        for node, expression in pending_bindings:
            references = self.named_master_refs(expression, exclude=node)
            references.update({label: parent for label, parent in local_refs.items() if parent != node})
            self.parser.bind(node, expression, references=references)
            if self.graph.nodes[node]['confidence'] == 'review' and '自引用' in self.graph.nodes[node].get('note', ''):
                self.parser.warn('expression-cycle', '图表表达式存在自引用：' + self.graph.nodes[node]['label'])
        for i, child in enumerate(children):
            self.walk_object(child, child_file, child_pointer + f'/qChildren/{i}', sheet, seen | ({extends} if extends else set()))

    def add_usage(self, sheet, chart_id, chart_title, chart_type, kind, index, part,
                  expression, original_label, parent, ref, master_id):
        label = friendly_label(original_label, expression)
        node = self.graph.add('usage', (sheet['id'], chart_id, kind, index, part), label,
                              expression=expression, ref=ref, chartTitle=chart_title,
                              sheetTitle=sheet['title'], masterId=master_id)
        self.graph.link(parent, node)
        self.fields[node] = dict(id=node, label=label, originalLabel=original_label,
                                 expression=expression, kind=kind, chartId=chart_id,
                                 chartTitle=chart_title, chartType=chart_type,
                                 sheetId=sheet['id'], sheetTitle=sheet['title'], masterId=master_id)
        sheet['fields'].append(node)

    def summary_stats(self) -> dict:
        counts = Counter(f['status'] for f in self.fields.values())
        source_nodes = [n for n in self.graph.nodes.values() if n['kind'] == 'source']
        tables = {n['table'] for n in source_nodes if n.get('sourceType') == 'database'}
        tables.update(r['table'] for r in self.parser.references.values())
        return dict(sheets=len(self.sheets), charts=len(self.charts), fields=len(self.fields),
                    variables=len(self.variables), masterItems=len(self.master_defs),
                    sourceTables=len(tables), sqlBlocks=sum(b['kind'] == 'sql' for b in self.parser.blocks),
                    loadBlocks=sum(b['kind'] == 'load' for b in self.parser.blocks),
                    complete=counts['complete'], partial=counts['partial'], unresolved=counts['unresolved'],
                    coverage=round(counts['complete'] / max(1, len(self.fields)) * 100),
                    warnings=len(self.warnings), extensions=dict(self.extensions))

    def summary(self) -> dict:
        return dict(id=self.id, name=self.name, folder=self.folder, stream=self.stream,
                    lastReload=self.last_reload, stats=self.stats, estimate=estimate(self),
                    sheets=[{k: v for k, v in s.items() if k != 'fields'} for s in self.sheets])

    def detail(self) -> dict:
        return dict(**self.summary(), fields=list(self.fields.values()),
                    warnings=self.warnings, charts=self.charts,
                    variables=[dict(name=name, id=node, expression=self.graph.nodes[node]['expression'])
                               for name, node in self.variables.items()])

    def source_file(self, filename: str) -> dict:
        # Only expose files already read into this immutable import snapshot.
        if filename not in self.files:
            raise ValueError('该文件不在当前 App 的导入快照中。')
        text = self.files[filename]
        if filename not in self.source_locations:
            pointers = {node['ref'].get('pointer', '') for node in self.graph.nodes.values()
                        if (node.get('ref') or {}).get('file') == filename}
            self.source_locations[filename] = json_locations(text, pointers) if filename in self.documents else {}
        return dict(file=filename, content=text, lineCount=text.count('\n') + 1,
                    locations=self.source_locations[filename])

    def original_code(self, ref: dict | None) -> str:
        original = ''
        if ref and ref['file'] in self.files:
            if ref['file'].endswith('.json'):
                value = self.documents[ref['file']]
                try:
                    for part in ref.get('pointer', '').strip('/').split('/'):
                        if not part: continue
                        part = part.replace('~1', '/').replace('~0', '~')
                        value = value[int(part)] if isinstance(value, list) else value[part]
                    original = json.dumps(value, ensure_ascii=False, indent=2)
                except (KeyError, IndexError, ValueError, TypeError):
                    original = 'JSON 路径无法解析；请重新导入元数据。'
            else:
                original = '\n'.join(self.files[ref['file']].splitlines()[ref['line'] - 1:ref['endLine']])
        return original

    def definition_sources(self, node_id: str) -> list[dict]:
        """Keep generated model fields distinct from their nearest real definitions."""
        node = self.graph.nodes[node_id]
        if node['kind'] != 'field' or node.get('ref'):
            return []
        seen, sources = {node_id}, {}
        pending = deque(sorted(self.graph.incoming.get(node_id, ())))
        while pending:
            current = pending.popleft()
            if current in seen:
                continue
            seen.add(current)
            definition = self.graph.nodes[current]
            ref = definition.get('ref')
            if ref:
                original = self.original_code(ref)
                if original:
                    identity = (ref['file'], ref.get('line', 0), ref.get('endLine', 0), ref.get('pointer', ''))
                    sources.setdefault(identity, dict(id=current, kind=definition['kind'], label=definition['label'],
                        ref=ref, original=original, parameterized=definition.get('parameterized', False)))
                # Do not replace a missing definition with a more distant input file.
                continue
            pending.extend(sorted(self.graph.incoming.get(current, ())))
        return [sources[identity] for identity in sorted(sources)]

    def evidence(self, node_id: str) -> dict:
        node = self.graph.nodes[node_id]
        return dict(**node, original=self.original_code(node.get('ref')),
                    definitionSources=self.definition_sources(node_id),
                    upstream=len(self.graph.incoming.get(node_id, ())),
                    downstream=len(self.graph.outgoing.get(node_id, ())),
                    inputs=[{k: v for k, v in parent.items() if k != 'expression'}
                            for parent in self.graph.nodes.values()
                            if parent['id'] in self.graph.incoming.get(node_id, ())])


class Catalog:
    def __init__(self, root: str | Path, *, allow_empty: bool = False) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir(): raise ValueError('元数据目录不存在：' + str(self.root))
        # Stop at App boundaries; never mistake objects/ or a Stream directory
        # for an App. Accept flat exports, Stream/App, and an outer apps/ wrapper.
        folders, pending, visited = [], [self.root], set()
        while pending:
            path = pending.pop()
            resolved = path.resolve()
            if resolved in visited or not resolved.is_relative_to(self.root): continue
            visited.add(resolved)
            if (path / 'app-properties.json').is_file() or (path / 'script.qvs').is_file():
                folders.append(path)
            else:
                pending.extend(p for p in sorted(path.iterdir(), reverse=True) if p.is_dir())
        self.apps: dict[str, Application] = {}
        self.errors: list[dict] = []
        for path in folders:
            parts = list(path.relative_to(self.root).parts)
            if parts and parts[0].casefold() == 'apps' and len(parts) > 1: parts = parts[1:]
            relative = '/'.join(parts) or path.name
            stream_name = parts[-2] if len(parts) > 1 else ''
            try:
                app = Application(path, identity=relative, stream_name=stream_name, folder=relative)
                if app.id in self.apps: raise ValueError('重复的 App 导出身份：' + relative)
                self.apps[app.id] = app
            except Exception as error:
                self.errors.append(dict(app=path.name, folder=relative, stream=stream_info({}, stream_name),
                                        message=f'{type(error).__name__}: {error}'))
        if not self.apps and (not allow_empty or folders):
            raise ValueError('目录中未找到可解析的 Qlik 导出 App。' + str(self.errors[:3]))
        self.imported_at = datetime.now(timezone.utc).isoformat()

    def summary(self) -> dict:
        apps = [app.summary() for app in self.apps.values()]
        streams = {}
        for item, is_error in [(a, False) for a in apps] + [(e, True) for e in self.errors]:
            stream = item['stream']
            group = streams.setdefault(stream['id'], dict(**stream, appCount=0, errorCount=0))
            group['errorCount' if is_error else 'appCount'] += 1
        return dict(root=str(self.root), importedAt=self.imported_at, apps=apps, errors=self.errors,
                    streams=sorted(streams.values(), key=lambda s: (s['source'] == 'unknown', s['name'].casefold())),
                    totals=dict(apps=len(apps), sheets=sum(a['stats']['sheets'] for a in apps),
                                fields=sum(a['stats']['fields'] for a in apps),
                                charts=sum(a['stats']['charts'] for a in apps),
                                variables=sum(a['stats']['variables'] for a in apps),
                                streams=sum(stream['source'] != 'unknown' for stream in streams.values())))

    def sources(self, stream_id: str = '') -> list[dict]:
        sources = {}
        def record(app, connection, table, source_type, fields):
            identity = (connection, table, source_type)
            item = sources.setdefault(identity, dict(id=key(*identity), table=table,
                                                     connection=connection, type=source_type, fields=set(), apps={}))
            item['fields'].update(fields)
            item['apps'][app.id] = dict(id=app.id, name=app.name, stream=app.stream)
        for app in self.apps.values():
            if stream_id and app.stream['id'] != stream_id: continue
            for reference in app.parser.references.values():
                record(app, reference['connection'], reference['table'], 'database', reference['fields'])
            for node in app.graph.nodes.values():
                if node['kind'] != 'source': continue
                record(app, node.get('connection', ''), node['table'], node.get('sourceType', 'database'), [node['field']])
        return sorted([dict(**{k: v for k, v in s.items() if k not in ('fields', 'apps')},
                            fields=sorted(s['fields']), apps=list(s['apps'].values())) for s in sources.values()],
                      key=lambda x: (-len(x['apps']), x['table']))
