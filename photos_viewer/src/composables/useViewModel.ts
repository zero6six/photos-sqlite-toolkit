/* ============ 视图模型：筛选/排序/展开/自定义列操作 ============ */
import { computed } from 'vue';
import { dataState, view, customCols, showToast } from '../state';
import type { Asset, Badges, AggState } from '../core/aggregate';
import { cleanV, kindLabel, srcLabel, gpsText, fmtBytes, fmtDur } from '../core/format';
import {
  colId, customValue, isNumericColumn, sortAssetList,
  isValidCustomColShape, revalidateCustomCols, type CustomCol,
} from './customCols';

/* 固定列排序取值（与旧版 computeRowVals 字段一一对应） */
export function rowValue(a: Asset, key: string): string {
  const f = a.f;
  switch (key) {
    case 'zpk':         return cleanV(f.zpk);
    case 'filename':    return cleanV(f.filename);
    case 'kindLabel':   return kindLabel(f);
    case 'dateCreated': return cleanV(f.dateCreated);
    case 'dateAdded':   return cleanV(f.dateAdded);
    case 'srcLabel':    return srcLabel(a);
    case 'albumTitle':  return cleanV(f.albumTitle);
    case 'gpsLabel':    return gpsText(f);
    case 'sizeLabel':   return fmtBytes(f.fileSize);
    case 'durLabel':    return fmtDur(f.duration);
    default:            return '';
  }
}

/** 当前筛选 + 排序后的可见资产列表 */
export const visibleAssets = computed<Asset[]>(() => {
  const S = dataState.value;
  if (!S) return [];
  const q = view.q.trim().toLowerCase();
  const list = S.assets.filter(a => {
    if (q && !a.searchText.includes(q)) return false;
    for (const c of view.chips) if (!a.badges[c as keyof Badges]) return false;
    if (view.walFilter && a.f.walStatus !== view.walFilter) return false;
    return true;
  });
  const key = view.sortKey;
  if (key.startsWith('custom:')) {
    const col = customCols.value.find(c => colId(c) === key.slice('custom:'.length));
    if (!col) return list;
    const vals = new Map<Asset, string>();
    for (const a of list) vals.set(a, customValue(S, a, col));
    return sortAssetList(list, {
      key, dir: view.sortDir,
      getVal: a => vals.get(a) ?? '',
      numeric: isNumericColumn([...vals.values()]),
    });
  }
  return sortAssetList(list, {
    key, dir: view.sortDir,
    getVal: a => rowValue(a, key),
    numeric: key === 'sizeLabel' || key === 'durLabel',
  });
});

/** 表头点击：同键翻转方向，换键重置为升序 */
export function sortByKey(k: string): void {
  if (view.sortKey === k) view.sortDir = view.sortDir === 1 ? -1 : 1;
  else { view.sortKey = k; view.sortDir = 1; }
}

/** 行点击：展开/收起详情 */
export function toggleOpen(key: string): void {
  if (view.openKeys.has(key)) view.openKeys.delete(key);
  else view.openKeys.add(key);
}

/* ---- 自定义列操作（防重复 + localStorage 持久化） ---- */
const LS_KEY = 'photosViewer.customCols.v1';

function hasLocalStorage(): boolean { return typeof localStorage !== 'undefined'; }

export function persistCustomCols(): void {
  if (!hasLocalStorage()) return;
  try { localStorage.setItem(LS_KEY, JSON.stringify(customCols.value)); } catch { /* 隐私模式等场景忽略 */ }
}

/** 载入新文件时回显持久化列：形状过滤 → 按新表头校验 → 按 id 去重 */
export function loadCustomCols(S: AggState): void {
  if (!hasLocalStorage()) { customCols.value = []; return; }
  try {
    const raw = localStorage.getItem(LS_KEY);
    const arr = raw ? JSON.parse(raw) as unknown[] : [];
    if (!Array.isArray(arr)) { customCols.value = []; return; }
    const seen = new Set<string>();
    customCols.value = revalidateCustomCols(arr.filter(isValidCustomColShape), S)
      .filter(c => { const id = colId(c); if (seen.has(id)) return false; seen.add(id); return true; });
  } catch { customCols.value = []; }
}

export function isColAdded(id: string): boolean {
  return customCols.value.some(c => colId(c) === id);
}

/** 添加单列；已存在则 toast 提示并返回 false */
export function addCustomCol(col: CustomCol): boolean {
  if (isColAdded(colId(col))) { showToast(`「${col.label}」已在列中`); return false; }
  customCols.value.push(col);
  persistCustomCols();
  showToast(`已添加列「${col.label}」`);
  return true;
}

/** 批量添加（分类「＋全部字段」）：跳过已存在项，单条汇总提示 */
export function addCustomCols(cols: CustomCol[], catName: string): void {
  let added = 0, skipped = 0;
  for (const c of cols) {
    if (isColAdded(colId(c))) { skipped++; continue; }
    customCols.value.push(c); added++;
  }
  if (added > 0) persistCustomCols();
  showToast(added > 0
    ? `${catName}：已添加 ${added} 列${skipped > 0 ? `（跳过 ${skipped} 列已存在）` : ''}`
    : `${catName}：列均已存在`);
}

/** 表头 ✕ 移除；若正按该列排序则回退默认排序 */
export function removeCustomCol(col: CustomCol): void {
  const id = colId(col);
  customCols.value = customCols.value.filter(c => colId(c) !== id);
  if (view.sortKey === 'custom:' + id) { view.sortKey = 'dateCreated'; view.sortDir = 1; }
  persistCustomCols();
}

/** 自定义列单元格：截断展示 + 悬停全文 */
export function customCell(state: AggState, a: Asset, c: CustomCol): { text: string; full: string } {
  const full = customValue(state, a, c);
  if (full === '') return { text: '', full: '' };
  return { text: full.length > 40 ? full.slice(0, 40) + '…' : full, full };
}
