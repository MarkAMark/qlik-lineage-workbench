import { ChevronRight } from 'lucide-react';
import { FIELD_KIND } from './components';
import type { Field } from './types';

const CHART_TYPES: Record<string, string> = {
  linechart: '折线图', barchart: '柱状图', combochart: '组合图', piechart: '饼图',
  table: '表格', 'pivot-table': '透视表', filterpane: '筛选器', kpi: 'KPI',
  scatterplot: '散点图', treemap: '树状图', gauge: '仪表图', map: '地图',
  waterfallchart: '瀑布图', histogram: '直方图', boxplot: '箱线图',
  distributionplot: '分布图', 'text-image': '文本与图片', container: '容器',
};

export default function FieldUsagePath({ field }: { field: Field }) {
  const kind = FIELD_KIND[field.kind] || '字段';
  const chartType = CHART_TYPES[field.chartType] || field.chartType;
  return <ol className="field-usage-path" aria-label="字段展示层级">
    <li data-level="sheet"><span className="usage-level-label">Sheet：</span><strong>{field.sheetTitle || '未命名 Sheet'}</strong></li>
    <li data-level="chart"><ChevronRight size={14} aria-hidden="true" /><span className="usage-level-label">图表：</span><strong title={`图表：${field.chartTitle || '未命名图表'}${field.chartId ? '\n图表 ID：' + field.chartId : ''}`}>{field.chartTitle || '未命名图表'}</strong>{chartType && <small className="usage-chart-type">（{chartType}）</small>}</li>
    <li data-level="field" aria-current="true"><ChevronRight size={14} aria-hidden="true" /><span className="usage-level-label">{kind}：</span><strong>{field.label || `未命名${kind}`}</strong></li>
  </ol>;
}
