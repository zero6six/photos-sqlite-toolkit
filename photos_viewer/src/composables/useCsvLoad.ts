/* ============ 加载入口 ============ */
import { dataState, resetView, showError } from '../state';
import { parseCSV } from '../core/csv';
import { aggregate } from '../core/aggregate';
import { loadCustomCols } from './useViewModel';

export function loadCSVText(text: string, fileName = ''): void {
  const rows = parseCSV(text);
  if (rows.length < 2) throw new Error('CSV 至少需要表头和一行数据');
  const headerLen = rows[0].length;
  for (let i = 1; i < rows.length; i++)
    if (rows[i].length !== headerLen)
      throw new Error(`第 ${i + 1} 行列数(${rows[i].length})与表头(${headerLen})不一致，可能不是本工具预期的导出格式`);
  const S = aggregate(rows, rows[0]);
  S.fileName = fileName;
  dataState.value = S;
  resetView();
  loadCustomCols(S);
}

export function readFile(file: File): void {
  const fr = new FileReader();
  fr.onload = () => {
    try { loadCSVText(String(fr.result), file.name); }
    catch (e) { showError('解析失败：' + (e instanceof Error ? e.message : String(e))); }
  };
  fr.onerror = () => showError('文件读取失败');
  fr.readAsText(file, 'utf-8');
}
