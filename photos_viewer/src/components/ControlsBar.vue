<script setup lang="ts">
import type { AggState, Badges } from '../core/aggregate';
import { view } from '../state';

const props = defineProps<{ state: AggState }>();

interface ChipDef { k: string; label: string }
const CHIP_DEFS: ChipDef[] = [
  { k: 'trashed', label: '已删除' }, { k: 'hidden', label: '已隐藏' },
  { k: 'fav', label: '已收藏' }, { k: 'gps', label: '含GPS' },
  { k: 'third', label: '第三方存入' }, { k: 'video', label: '视频' }, { k: 'photo', label: '照片' },
];

/* 与"视频"互补的照片 chip 省略；该语义不存在(计数0)的 chip 自动隐藏 */
const chips = CHIP_DEFS
  .filter(d => d.k !== 'photo')
  .map(d => ({ ...d, n: props.state.assets.filter(a => a.badges[d.k as keyof Badges]).length }))
  .filter(d => d.n > 0);

function toggleChip(k: string): void {
  if (view.chips.has(k)) view.chips.delete(k);
  else view.chips.add(k);
}

/* WAL 差分筛选：CSV 带 wal-diff-status 列才出现，只列有量的状态 */
interface WalOpt { k: string; label: string }
const WAL_OPTS: WalOpt[] = [
  { k: 'added', label: '➕ WAL新增' },
  { k: 'removed', label: '🗑 WAL删除' },
  { k: 'modified', label: '✏️ WAL修改' },
];
const walChips = WAL_OPTS
  .map(d => ({ ...d, n: props.state.assets.filter(a => a.f.walStatus === d.k).length }))
  .filter(d => d.n > 0);

function toggleWal(k: string): void {
  view.walFilter = view.walFilter === k ? '' : k;
}
</script>

<template>
  <input id="q" type="search" placeholder="搜索 文件名 / UUID / App / 相册…" v-model="view.q">
  <span class="sep"></span>
  <span id="chips">
    <span v-for="c in chips" :key="c.k" class="chip" :class="{ on: view.chips.has(c.k) }"
          @click="toggleChip(c.k)">{{ c.label }}<span class="n">{{ c.n }}</span></span>
  </span>
  <span class="sep"></span>
  <span v-if="walChips.length" id="walchips" title="WAL 差分导出（photos_sqlite_export ≥0.2.0）的状态筛选：点击只看对应状态的资产">
    <span v-for="c in walChips" :key="c.k" class="chip" :class="{ on: view.walFilter === c.k }"
          @click="toggleWal(c.k)">{{ c.label }}<span class="n">{{ c.n }}</span></span>
  </span>
  <span v-if="walChips.length" class="sep"></span>
  <label class="pick-toggle" title="勾选后进入选列模式：点击条目详情面板中的字段/分类即可将其添加为主表格列；已添加列可点表头 ✕ 移除">
    <input type="checkbox" v-model="view.pick">动态自定义列
  </label>
</template>
