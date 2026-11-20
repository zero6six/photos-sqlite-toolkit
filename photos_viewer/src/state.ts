/* ============ 全局轻量状态（单实例应用，模块级单例即可） ============ */
import { reactive, ref, shallowRef } from 'vue';
import type { AggState } from './core/aggregate';
import type { CustomCol } from './composables/customCols';

/** aggregate() 的结果；null = 尚未载入文件 */
export const dataState = shallowRef<AggState | null>(null);

export interface ViewState {
  q: string;
  chips: Set<string>;
  walFilter: string;        // WAL差分筛选：''=全部 / added|removed|modified
  sortKey: string;          // 固定列键 或 'custom:<id>'
  sortDir: 1 | -1;
  openKeys: Set<string>;
  pick: boolean;            // 「动态自定义列」选列模式
}
export const view = reactive<ViewState>({
  q: '', chips: new Set(), walFilter: '', sortKey: 'dateCreated', sortDir: 1, openKeys: new Set(), pick: false,
});

/** 用户动态添加的自定义列（持久化到 localStorage） */
export const customCols = ref<CustomCol[]>([]);

export const toastMsg = ref('');
export const errMsg = ref('');

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function showToast(msg: string): void {
  toastMsg.value = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastMsg.value = ''; }, 2600);
}
let errTimer: ReturnType<typeof setTimeout> | undefined;
export function showError(msg: string): void {
  errMsg.value = msg;
  clearTimeout(errTimer);
  errTimer = setTimeout(() => { errMsg.value = ''; }, 6000);
}

/** 载入新文件时重置视图状态（自定义列由 loadCustomCols 按新表头校验回显） */
export function resetView(): void {
  view.q = '';
  view.chips.clear();
  view.walFilter = '';
  view.sortKey = 'dateCreated';
  view.sortDir = 1;
  view.openKeys.clear();
  view.pick = false;
}
