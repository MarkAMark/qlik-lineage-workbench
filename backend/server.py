from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import os
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .assessment import estimate
from .catalog import Catalog

PROJECT = Path(__file__).resolve().parent.parent


def csv_value(value) -> str:
    text = str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        # Windows SO_REUSEADDR can permit multiple listeners for the same endpoint,
        # which would serve different catalog snapshots from one workbench address.
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, catalog: Catalog):
        super().__init__(address, Handler)
        self.catalog = catalog
        self.import_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, fmt, *args):
        # Do not log paths, search expressions or metadata to stdout.
        if args and str(args[1] if len(args) > 1 else '') in ('500',):
            print('Local API error', flush=True)

    def send(self, body: bytes, content_type: str, status: int = 200,
             filename: str = '') -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if filename: self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def json(self, value, status=200, filename='') -> None:
        self.send(json.dumps(value, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status, filename)

    def valid_host(self) -> bool:
        try: return urlsplit('http://' + self.headers.get('Host', '')).hostname in ('127.0.0.1', 'localhost')
        except ValueError: return False

    def do_GET(self):
        if not self.valid_host():
            self.json(dict(error='仅允许 localhost 访问。'), 403)
            return
        parsed = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path = parsed.path
        catalog = self.server.catalog  # One immutable snapshot per request.
        try:
            if query.get('snapshot') and query['snapshot'] != catalog.imported_at:
                self.json(dict(error='元数据快照已更新，请刷新页面后重新选择。'), 409)
                return
            if path == '/api/health':
                self.json(dict(status='ok', service='qlik-lineage-studio', apps=len(catalog.apps), importedAt=catalog.imported_at))
            elif path == '/api/catalog': self.json(catalog.summary())
            elif path == '/api/app': self.json(catalog.apps[query['id']].detail())
            elif path == '/api/source-file':
                result = catalog.apps[query['app']].source_file(query['file'])
                self.json(dict(**result, snapshot=catalog.imported_at))
            elif path in ('/api/table-lineage', '/api/table-detail', '/api/table-evidence',
                           '/api/table-field-lineage', '/api/table-relations.csv'):
                app = catalog.apps[query['app']]
                tables = app.table_lineage
                offset, limit = int(query.get('offset', 0)), int(query.get('limit', 200))
                if offset < 0 or not 1 <= limit <= 1000:
                    raise ValueError('无效的分页范围。')
                if path == '/api/table-detail':
                    result = tables.detail(query['table'], offset=offset, limit=limit, query=query.get('q', ''))
                elif path == '/api/table-evidence':
                    result = tables.evidence(query['edge'], offset=offset, limit=limit)
                elif path == '/api/table-field-lineage':
                    result = tables.field_trace(query['version'], query['field'])
                else:
                    result = tables.view(scope=query.get('scope', 'app'), usage=query.get('usage', ''),
                        sheet=query.get('sheet', ''), chart=query.get('chart', ''),
                        version=query.get('version', ''), field=query.get('field', ''),
                        include_context=query.get('context', '1') != '0')
                result['snapshot'] = catalog.imported_at
                result['appStream'] = app.stream
                if path.endswith('.csv'):
                    selected_edges = set(query['edges'].split(',')) if 'edges' in query else None
                    if selected_edges is not None and selected_edges - {e['id'] for e in result['edges']} - {'none'}:
                        raise ValueError('导出关系已失效。')
                    output = io.StringIO(newline='')
                    writer = csv.writer(output)
                    writer.writerow(['Snapshot', 'Scope', 'App', 'Source', 'Source version', 'Target', 'Target version',
                                     'Roles', 'Operations', 'Status', 'File', 'Line', 'End line', 'Edge ID', 'Source ID', 'Target ID', 'Stream'])
                    by_id = {node['id']: node for node in result['nodes']}
                    for edge in result['edges']:
                        if selected_edges is not None and edge['id'] not in selected_edges:
                            continue
                        source, target = by_id[edge['source']], by_id[edge['target']]
                        operations = tables.operation_details(edge['operationIds']) or [dict(kinds=edge['operationKinds'], ref=target.get('ref', {}))]
                        for operation in operations:
                            ref = operation['ref']
                            writer.writerow([csv_value(v) for v in [catalog.imported_at, result['scope'], app.name,
                                source['label'], source['version'], target['label'], target['version'],
                                '; '.join(edge['roles']), '; '.join(operation['kinds']), edge['status'],
                                ref.get('file', ''), ref.get('line', ''), ref.get('endLine', ''),
                                edge['id'], edge['source'], edge['target'], app.stream['name']]])
                    self.send(output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', filename='qlik-table-lineage.csv')
                else:
                    self.json(result)
            elif path == '/api/lineage':
                app = catalog.apps[query['app']]
                field = query['field']
                if field not in app.fields: raise KeyError('field')
                self.json(dict(**app.graph.trace(field), field=app.fields[field], appName=app.name,
                               boundaries=app.warnings, appStream=app.stream))
            elif path == '/api/evidence':
                app = catalog.apps[query['app']]
                node_id = query['node']
                result = app.evidence(node_id)
                seen, stack = set(), [node_id]
                while stack:
                    node = stack.pop()
                    if node in seen: continue
                    seen.add(node)
                    stack.extend(app.graph.outgoing.get(node, ()))
                result['consumers'] = [f for k, f in app.fields.items() if k in seen]
                self.json(result)
            elif path == '/api/sources': self.json(catalog.sources(query.get('stream', '')))
            elif path == '/api/search':
                text = query.get('q', '').strip().casefold()
                matches = []
                if text:
                    for app in catalog.apps.values():
                        if query.get('stream') and app.stream['id'] != query['stream']: continue
                        for field in app.fields.values():
                            haystack = ' '.join(str(field.get(k, '')) for k in ('label', 'expression', 'sheetTitle', 'chartTitle')) + ' ' + app.name + ' ' + app.stream['name']
                            if text in haystack.casefold():
                                matches.append(dict(**field, appId=app.id, appName=app.name, stream=app.stream))
                self.json(dict(total=len(matches), results=matches[:80]))
            elif path in ('/api/assessment', '/api/report.json', '/api/report.csv'):
                settings = dict(hours_per_day=float(query.get('hoursPerDay', 8)),
                                contingency=float(query.get('contingency', 25)),
                                productivity=float(query.get('productivity', 1)))
                rows = [dict(**estimate(app, **settings), stats=app.stats, warnings=app.warnings, stream=app.stream)
                        for app in catalog.apps.values() if not query.get('stream') or app.stream['id'] == query['stream']]
                result = dict(importedAt=catalog.imported_at, settings=settings, apps=rows,
                              totals={k: round(sum(r[k] for r in rows), 1)
                                      for k in ('lowDays', 'likelyDays', 'highDays')},
                              note='静态元数据 ROM 估算；未校准；跨 App 工时相加尚未扣除复用。')
                if path.endswith('.csv'):
                    output = io.StringIO(newline='')
                    writer = csv.writer(output)
                    writer.writerow(['App', 'Sheets', 'Field uses', 'Unique expressions', 'High risk expressions',
                                     'Complete trace %', 'Low person-days', 'Likely person-days', 'High person-days',
                                     'Hours per day', 'Contingency %', 'Complexity factor', 'Estimate basis', 'Stream'])
                    for row in rows:
                        writer.writerow([csv_value(v) for v in [row['appName'], row['stats']['sheets'],
                            row['stats']['fields'], row['uniqueExpressions'], row['highRisk'], row['stats']['coverage'],
                            row['lowDays'], row['likelyDays'], row['highDays'], row['hoursPerDay'],
                            row['contingency'], row['productivity'], 'ROM; uncalibrated; excludes view internals, platform setup, UAT waiting; app-level dedup only', row['stream']['name']]])
                    self.send(output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', filename='quicksight-migration-assessment.csv')
                else:
                    self.json(result, filename='quicksight-migration-assessment.json' if path.endswith('.json') else '')
            elif path == '/api/fields.csv':
                selected = [catalog.apps[query['app']]] if query.get('app') else catalog.apps.values()
                output = io.StringIO(newline='')
                writer = csv.writer(output)
                writer.writerow(['App', 'Sheet', 'Chart', 'Kind', 'Label', 'Qlik expression', 'Master ID',
                                 'Trace status', 'Risk', 'Risk reasons', 'Source tables', 'Stream'])
                for app in selected:
                    for field in app.fields.values():
                        sources = sorted({app.graph.nodes[n]['table'] for n in app.graph.ancestors(field['id'])
                                          if app.graph.nodes[n]['kind'] == 'source'})
                        writer.writerow([csv_value(v) for v in [app.name, field['sheetTitle'], field['chartTitle'],
                            field['kind'], field['label'], field['expression'], field['masterId'], field['status'],
                            field['risk']['level'], '; '.join(i['title'] for i in field['risk']['issues']), '; '.join(sources), app.stream['name']]])
                self.send(output.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', filename='qlik-field-inventory.csv')
            elif path.startswith('/api/'):
                self.json(dict(error='接口不存在。'), 404)
            else:
                relative = unquote(path).lstrip('/') or 'index.html'
                dist = (PROJECT / 'dist').resolve()
                target = (dist / relative).resolve()
                if not target.is_relative_to(dist):
                    self.json(dict(error='无效路径。'), 400)
                elif not target.is_file():
                    self.json(dict(error='前端尚未构建或文件不存在。请运行 Setup.ps1。'), 404)
                else:
                    content_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                    self.send(target.read_bytes(), content_type)
        except (KeyError, ValueError, TypeError) as error:
            self.json(dict(error='请求参数无效或资源已更改：' + str(error)), 400)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        except Exception as error:
            self.json(dict(error='分析失败：' + type(error).__name__ + ' / ' + str(error)), 500)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Trace-Request') != 'local':
            self.json(dict(error='只接受本机工作台发起的导入。'), 403)
            return
        origin = self.headers.get('Origin')
        allowed = {f'http://{host}:{port}' for host in ('127.0.0.1', 'localhost')
                   for port in (self.server.server_port, 5173)}
        if origin and origin not in allowed:
            self.json(dict(error='请求来源无效。'), 403)
            return
        if self.path != '/api/import':
            self.json(dict(error='接口不存在。'), 404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384: raise ValueError('导入参数过长或为空。')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not isinstance(body.get('root', ''), str):
                raise ValueError('导入参数必须包含字符串格式的目录。')
            root = body.get('root') or str(self.server.catalog.root)
            if not self.server.import_lock.acquire(blocking=False):
                self.json(dict(error='已有导入正在进行，请稍后重试。'), 409)
                return
            try:
                updated = Catalog(root)
                self.server.catalog = updated
            finally: self.server.import_lock.release()
            self.json(updated.summary())
        except (ValueError, OSError, TypeError) as error:
            self.json(dict(error=str(error)), 400)


def main():
    parser = argparse.ArgumentParser(description='Qlik lineage local workbench')
    default_root = PROJECT / 'metadata' / 'apps'
    parser.add_argument('--metadata-root', default=os.environ.get('QLIK_METADATA_ROOT', str(default_root)))
    parser.add_argument('--port', type=int, default=8775)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    print('Importing local Qlik metadata...', flush=True)
    root = Path(args.metadata_root).expanduser().resolve()
    if root == default_root.resolve():
        root.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(root, allow_empty=root == default_root.resolve())
    server = LocalServer(('127.0.0.1', args.port), catalog)
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Trace ready: {url} / {len(catalog.apps)} apps. Ctrl+C to stop.', flush=True)
    if args.open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__': main()
