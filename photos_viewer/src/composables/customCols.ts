/* ============ 动态自定义列：取值/排序/校验（纯逻辑，无 DOM/Vue 依赖） ============
 * 三种列：
 *  - field: 逻辑字段（FIELD_DEFS 中的 key，如 cameraModel）
 *  - raw:   原始 CSV 列（按原始列名引用，跨文件回验）
 *  - cat:   分类拼接列（如「设备」= 分类内各字段展示值以 ' · ' 连接）
 */
import { FIELD_DEFS, CAT_NAMES } from '../core/schema';
import { firstNonEmpty, type AggState, type Asset } from '../core/aggregate';
import { cleanV, fieldDisplay } from '../core/format';

export type CustomColKind = 'field' | 'raw' | 'cat';
export interface CustomCol { kind: CustomColKind; key: string; label: string }

export const colId = (c: CustomCol): string => `${c.kind}:${c.key}`;

export function fieldLabel(key: string): string {
  return FIELD_DEFS.find(d => d.k === key)?.label ?? key;
}
export function makeFieldCol(key: string): CustomCol { return { kind: 'field', key, label: fieldLabel(key) }; }
export function makeRawCol(headerName: string): CustomCol { return { kind: 'raw', key: headerName, label: headerName }; }
export function makeCatCol(cat: string): CustomCol { return { kind: 'cat', key: cat, label: CAT_NAMES[cat] ?? cat }; }

/** 分类拼接值：分类内已映射字段的展示值(含语义美化)非空以 ' · ' 连接 */
export function catValue(state: AggState, a: Asset, cat: string): string {
  const parts: string[] = [];
  for (const d of FIELD_DEFS) {
    if (d.cat !== cat || state.m.map[d.k] === undefined) continue;
    const v = fieldDisplay(d.k, cleanV(a.f[d.k]));
    if (v !== '') parts.push(v);
  }
  return parts.join(' · ');
}

/** 资产在该自定义列上的完整文本值（未截断；'' = 缺失，展示层负责空值兜底） */
export function customValue(state: AggState, a: Asset, col: CustomCol): string {
  if (col.kind === 'field') return cleanV(a.f[col.key]);
  if (col.kind === 'cat') return catValue(state, a, col.key);
  const idx = state.headers.indexOf(col.key);
  if (idx < 0) return '';
  return cleanV(firstNonEmpty(a.rows, idx));
}

/** 数值列检测：非空值全部可解析为有限数值则按数值排序 */
export function isNumericColumn(values: string[]): boolean {
  const nonEmpty = values.filter(v => v !== '');
  return nonEmpty.length > 0 && nonEmpty.every(v => isFinite(parseFloat(v)));
}

/** 空值恒排末尾（与固定列一致，升/降序均如此）；tiebreak 用 zPK 数值序保证稳定 */
export function sortAssetList(
  list: Asset[],
  opts: { key: string; dir: 1 | -1; getVal: (a: Asset) => string; numeric: boolean },
): Asset[] {
  const { key, dir, getVal, numeric } = opts;
  return [...list].sort((a, b) => {
    const va = getVal(a), vb = getVal(b);
    if (va === '' && vb !== '') return 1;
    if (vb === '' && va !== '') return -1;
    const na = parseFloat(va), nb = parseFloat(vb);
    let d: number;
    if (numeric || (key === 'zpk' && isFinite(na) && isFinite(nb)))
      d = (isFinite(na) ? na : Infinity) - (isFinite(nb) ? nb : Infinity);
    else d = String(va || '').localeCompare(String(vb || ''), 'zh');
    return d * dir || String(a.f.zpk).localeCompare(String(b.f.zpk), undefined, { numeric: true }) * dir;
  });
}

/** localStorage 反序列化后的形状校验 */
export function isValidCustomColShape(c: unknown): c is CustomCol {
  if (!c || typeof c !== 'object') return false;
  const o = c as Record<string, unknown>;
  return (o.kind === 'field' || o.kind === 'raw' || o.kind === 'cat') &&
         typeof o.key === 'string' && o.key !== '' &&
         typeof o.label === 'string' && o.label !== '';
}

/** 加载持久化列时按当前数据校验：列在新文件中不存在的自动剔除 */
export function revalidateCustomCols(cols: CustomCol[], state: AggState): CustomCol[] {
  return cols.filter(c => {
    if (c.kind === 'field') return state.m.map[c.key] !== undefined;
    if (c.kind === 'raw') return state.headers.includes(c.key);
    return FIELD_DEFS.some(d => d.cat === c.key && state.m.map[d.k] !== undefined);
  });
}
