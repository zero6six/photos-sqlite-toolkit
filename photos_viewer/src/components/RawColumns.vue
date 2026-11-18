<script setup lang="ts">
import { ref } from 'vue';
import type { AggState, Asset } from '../core/aggregate';
import { cleanV, isBlobCol, looksPlist } from '../core/format';
import { view } from '../state';
import { makeRawCol } from '../composables/customCols';
import { addCustomCol, isColAdded } from '../composables/useViewModel';

const props = defineProps<{ state: AggState; asset: Asset }>();

/* 超长 blob 值的展开状态（列下标集合，按当前组件实例隔离） */
const expanded = ref(new Set<number>());
function toggleBlob(i: number): void {
  if (expanded.value.has(i)) expanded.value.delete(i);
  else expanded.value.add(i);
}

function rowValue(i: number): string { return cleanV(props.asset.rows[0][i]); }
function isRawAdded(name: string): boolean { return isColAdded('raw:' + name); }

function onRowClick(name: string): void {
  if (!view.pick) return;
  addCustomCol(makeRawCol(name));
}
</script>

<template>
  <details class="rawcols">
    <summary>▸ 显示全部 {{ state.headers.length }} 个原始列（含未映射列 {{ state.m.unmapped.length }} 个）</summary>
    <table class="subtbl">
      <tr v-for="(name, i) in state.headers" :key="i"
          :class="{ pickable: view.pick, added: view.pick && isRawAdded(name) }"
          :title="view.pick ? (isRawAdded(name) ? '已添加为列' : '点击将该原始列添加为主表格列') : undefined"
          @click="onRowClick(name)">
        <th style="width:260px;font-weight:500;color:var(--txt);text-align:left">{{ name }}</th>
        <td>
          <span v-if="rowValue(i) === ''" style="color:#cbd5e1">—</span>
          <span v-else-if="rowValue(i).length > 80" class="blob">
            <span v-if="isBlobCol(name) && looksPlist(rowValue(i))" class="blob-tag">二进制plist</span>{{ expanded.has(i) ? rowValue(i) : rowValue(i).slice(0, 80) + '…' }}<span class="expander" @click.stop="toggleBlob(i)">{{ expanded.has(i) ? '收起' : `展开全部 ${rowValue(i).length} 字符` }}</span>
          </span>
          <template v-else>{{ rowValue(i) }}</template>
        </td>
        <td v-if="view.pick" class="pick-mark-td">{{ isRawAdded(name) ? '✓已加列' : '＋加列' }}</td>
      </tr>
    </table>
  </details>
</template>
