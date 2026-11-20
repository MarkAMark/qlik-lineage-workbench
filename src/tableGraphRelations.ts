import type { AppDetail, TableGraph } from './types';

export type TableDirection = 'all' | 'upstream' | 'downstream' | 'both';

export function resolveTableSelection(app: Pick<AppDetail, 'sheets' | 'charts'>, sheet: string, chart: string, fallbackSheet = '', fallbackChart = '') {
  const selectedSheet = app.sheets.find(s => s.id === sheet) || app.sheets.find(s => s.id === fallbackSheet) || app.sheets.find(s => s.fieldCount > 0) || app.sheets[0];
  const charts = app.charts.filter(c => c.sheetId === selectedSheet?.id);
  return { sheet: selectedSheet?.id || '', chart: (charts.find(c => c.id === chart) || charts.find(c => c.id === fallbackChart) || charts[0])?.id || '' };
}

export function filterTableGraph(graph: TableGraph, focus: string, direction: TableDirection, depth: '1' | 'all'): TableGraph {
  if (direction === 'all' || !graph.nodes.some(node => node.id === focus)) return graph;
  const ids = new Set([focus]);
  const walk = (up: boolean) => {
    let frontier = [focus];
    const seen = new Set(frontier);
    while (frontier.length) {
      const next: string[] = [];
      for (const id of frontier) for (const edge of graph.edges) {
        if ((up ? edge.target : edge.source) !== id) continue;
        const peer = up ? edge.source : edge.target;
        if (seen.has(peer)) continue;
        seen.add(peer); ids.add(peer); next.push(peer);
      }
      if (depth === '1') break;
      frontier = next;
    }
  };
  if (direction === 'upstream' || direction === 'both') walk(true);
  if (direction === 'downstream' || direction === 'both') walk(false);
  return { ...graph, nodes: graph.nodes.filter(node => ids.has(node.id)),
    edges: graph.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)) };
}

export function tableNodeType(node: { kind: string; current: boolean; dropped: boolean; auxiliary: boolean }) {
  return node.kind === 'dataset' ? '图表逻辑数据集' : node.kind === 'table_source' ? '源资产' :
    node.kind === 'table_unresolved' ? '来源待确认' : node.auxiliary ? '辅助映射' :
    node.dropped ? '中间表 · 已删除' : node.current ? '最终逻辑表' : '历史版本';
}
