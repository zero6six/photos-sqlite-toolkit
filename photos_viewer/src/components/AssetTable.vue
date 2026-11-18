<script setup lang="ts">
import type { AggState } from '../core/aggregate';
import { cleanV, srcLabel, gpsParts, kindLabel, fmtBytes, fmtDur } from '../core/format';
import { view, customCols } from '../state';
import { visibleAssets, sortByKey, toggleOpen, removeCustomCol, customCell } from '../composables/useViewModel';
import { colId } from '../composables/customCols';
import TimeCell from './TimeCell.vue';
import Badges from './Badges.vue';
import DetailPanel from './DetailPanel.vue';

defineProps<{ state: AggState }>();

/* 固定列定义（与旧版 COLS 一致） */
const COLS: { k: string; label: string; cls?: string; nosort?: boolean }[] = [
  { k: 'zpk',         label: 'zPK',     cls: 'mono' },
  { k: 'filename',    label: '文件名' },
  { k: 'kindLabel',   label: '类型' },
  { k: 'dateCreated', label: '拍摄时间(当地)', cls: 'mono' },
  { k: 'dateAdded',   label: '入库时间(当地)', cls: 'mono' },
  { k: 'srcLabel',    label: '来源' },
  { k: 'albumTitle',  label: '相册' },
  { k: 'gpsLabel',    label: 'GPS',     cls: 'mono' },
  { k: 'sizeLabel',   label: '大小' },
  { k: 'durLabel',    label: '时长' },
  { k: 'badges',      label: '状态',    nosort: true },
];

function osmUrl(p: { lat: number; lon: number }): string {
  return `https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=17/${p.lat}/${p.lon}`;
}
</script>

<template>
  <div v-if="!visibleAssets.length" class="empty-tip">没有符合当前筛选条件的资产</div>
  <table v-else>
    <thead>
      <tr>
        <th v-for="c in COLS" :key="c.k" :class="[c.cls, { nosort: c.nosort }]"
            @click="!c.nosort && sortByKey(c.k)">
          {{ c.label }}<span v-if="view.sortKey === c.k" class="arrow"> {{ view.sortDir > 0 ? '▲' : '▼' }}</span>
        </th>
        <th v-for="cc in customCols" :key="colId(cc)" class="custom-col"
            :title="`自定义列（${cc.kind === 'field' ? '逻辑字段' : cc.kind === 'raw' ? '原始列' : '分类拼接'}）：点击排序，✕ 移除`"
            @click="sortByKey('custom:' + colId(cc))">
          {{ cc.label }}<span v-if="view.sortKey === 'custom:' + colId(cc)" class="arrow"> {{ view.sortDir > 0 ? '▲' : '▼' }}</span>
          <span class="rm" @click.stop="removeCustomCol(cc)">✕</span>
        </th>
      </tr>
    </thead>
    <tbody>
      <template v-for="a in visibleAssets" :key="a.key">
        <tr class="asset" :class="{ open: view.openKeys.has(a.key) }" @click="toggleOpen(a.key)">
          <td class="mono">{{ cleanV(a.f.zpk) }}</td>
          <td class="fn" :title="cleanV(a.f.origname) ? '原始文件名: ' + cleanV(a.f.origname) : cleanV(a.f.filename)">
            <template v-if="cleanV(a.f.filename)">{{ cleanV(a.f.filename) }}</template>
            <span v-else style="color:#cbd5e1">—</span>
            <small v-if="cleanV(a.f.origname) && cleanV(a.f.origname) !== cleanV(a.f.filename)">{{ cleanV(a.f.origname) }}</small>
          </td>
          <td>{{ kindLabel(a.f) }}</td>
          <td><TimeCell :utc-val="cleanV(a.f.dateCreated)" :f="a.f" :state="state" field-key="dateCreated" /></td>
          <td><TimeCell :utc-val="cleanV(a.f.dateAdded)" :f="a.f" :state="state" field-key="dateAdded" /></td>
          <td>{{ srcLabel(a) }}</td>
          <td>{{ cleanV(a.f.albumTitle) }}</td>
          <td class="mono">
            <a v-if="gpsParts(a.f)" :href="osmUrl(gpsParts(a.f)!)" target="_blank" rel="noopener">{{ gpsParts(a.f)!.lat.toFixed(5) }}, {{ gpsParts(a.f)!.lon.toFixed(5) }}</a>
            <span v-else style="color:#cbd5e1">—</span>
          </td>
          <td>{{ fmtBytes(a.f.fileSize) }}</td>
          <td>{{ fmtDur(a.f.duration) }}</td>
          <td><Badges :b="a.badges" /></td>
          <td v-for="cc in customCols" :key="colId(cc)" class="custom-cell" :title="customCell(state, a, cc).full">
            <template v-if="customCell(state, a, cc).text">{{ customCell(state, a, cc).text }}</template>
            <span v-else style="color:#cbd5e1">—</span>
          </td>
        </tr>
        <tr v-if="view.openKeys.has(a.key)" class="detail">
          <td :colspan="COLS.length + customCols.length"><DetailPanel :asset="a" :state="state" /></td>
        </tr>
      </template>
    </tbody>
  </table>
</template>
