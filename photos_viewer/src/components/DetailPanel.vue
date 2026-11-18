<script setup lang="ts">
import { computed } from 'vue';
import type { AggState, Asset } from '../core/aggregate';
import { FIELD_DEFS, CAT_ORDER, CAT_NAMES, type FieldDef } from '../core/schema';
import { cleanV, fieldDisplay, subTypeLabel, fmtBytes, sqliteUtcPlus, tzOffSeconds, tzLabel } from '../core/format';
import { view } from '../state';
import { makeFieldCol, makeCatCol } from '../composables/customCols';
import { addCustomCol, addCustomCols, isColAdded } from '../composables/useViewModel';
import RawColumns from './RawColumns.vue';

const props = defineProps<{ asset: Asset; state: AggState }>();

/* 需要附加"当地"换算行的时间字段：当地 = UTC值 + 记录时区偏移 */
const LOCAL_DERIVE: Record<string, string> = {
  dateCreated: '拍摄/创建时间', dateAdded: '入库(添加)时间',
  dateModified: '修改时间', dateTrashed: '移入删除时间',
};

const off = computed(() => tzOffSeconds(props.asset.f));
const offDesc = computed(() => off.value !== null ? (cleanV(props.asset.f.tzname) || tzLabel(off.value)) : '');

/** 该分类下已映射到 CSV 列的字段（可加列性 = 列存在，与本行是否有值无关） */
function defsOf(cat: string): FieldDef[] {
  return FIELD_DEFS.filter(d => d.cat === cat && props.state.m.map[d.k] !== undefined);
}
const cats = CAT_ORDER.filter(cat => defsOf(cat).length > 0);

function rawOf(k: string): string { return cleanV(props.asset.f[k]); }
function shownOf(k: string, v: string): string { return fieldDisplay(k, v); }

/* ---- 选列模式操作 ---- */
function isFieldAdded(k: string): boolean { return isColAdded('field:' + k); }
function catColAdded(cat: string): boolean { return isColAdded('cat:' + cat); }
function allFieldsAdded(cat: string): boolean { return defsOf(cat).every(d => isFieldAdded(d.k)); }

function onFieldClick(d: FieldDef): void {
  if (!view.pick) return;
  addCustomCol(makeFieldCol(d.k));
}
function addAllFields(cat: string): void {
  addCustomCols(defsOf(cat).map(d => makeFieldCol(d.k)), CAT_NAMES[cat] ?? cat);
}
function addCatCol(cat: string): void {
  if (catColAdded(cat)) { addCustomCol(makeCatCol(cat)); return; }   // 已存在 → toast 提示
  addCustomCol(makeCatCol(cat));
}
</script>

<template>
  <div>
    <div class="dgrid">
      <template v-for="cat in cats" :key="cat">
        <div class="cat-title-row">
          <div class="cat-title">{{ CAT_NAMES[cat] }}</div>
          <span v-if="view.pick" class="cat-ops">
            <button class="catop" :class="{ added: allFieldsAdded(cat) }" @click.stop="addAllFields(cat)">＋全部字段</button>
            <button class="catop" :class="{ added: catColAdded(cat) }" @click.stop="addCatCol(cat)">＋拼接成一列</button>
          </span>
        </div>
        <template v-for="d in defsOf(cat)" :key="d.k">
          <div v-if="view.pick || rawOf(d.k) !== ''"
               class="drow" :class="{ pickable: view.pick, added: view.pick && isFieldAdded(d.k) }"
               :title="view.pick ? (isFieldAdded(d.k) ? '已添加为列' : '点击将该字段添加为主表格列') : undefined"
               @click="onFieldClick(d)">
            <dt :title="'来源字段: ' + state.m.rawName[d.k]">{{ d.label }}</dt>
            <dd>
              <template v-if="rawOf(d.k) !== ''">{{ shownOf(d.k, rawOf(d.k)) }}</template>
              <span v-else style="color:#cbd5e1">—</span>
            </dd>
            <span v-if="view.pick" class="pick-mark">{{ isFieldAdded(d.k) ? '✓已加列' : '＋加列' }}</span>
          </div>
          <!-- "当地"换算行：仅源字段有值、含时区偏移且换算成功时出现；派生行不可加列 -->
          <div v-if="!view.pick && cat === 'time' && LOCAL_DERIVE[d.k] && off !== null && rawOf(d.k) !== '' && sqliteUtcPlus(rawOf(d.k), off)"
               class="drow">
            <dt :title="`换算: ${state.m.rawName[d.k]} 的UTC值 + 时区偏移 ${off}秒`">{{ LOCAL_DERIVE[d.k] }}(当地 {{ offDesc }})</dt>
            <dd>{{ sqliteUtcPlus(rawOf(d.k), off) }}</dd>
          </div>
        </template>
      </template>
    </div>

    <template v-if="asset.albums.length">
      <div class="cat-title">相册归属</div>
      <span v-for="(al, i) in asset.albums" :key="i" class="album-chip"
            :title="[al.guid && 'GUID: ' + al.guid, al.created && '创建: ' + al.created].filter(Boolean).join(' · ')">
        {{ al.title ? al.title : '(未命名相册)' }}
      </span>
      <span v-if="state.m.map.albumParent !== undefined && cleanV(asset.f.albumParent)"
            class="album-chip parent" title="父级">↳ {{ cleanV(asset.f.albumParent) }}</span>
    </template>

    <template v-if="asset.resources.length">
      <div class="cat-title">内部资源（{{ asset.resources.length }} 条，已按资源去重折叠）</div>
      <table class="subtbl">
        <tr><th>资源类型</th><th>子类型</th><th>大小</th><th>File ID</th><th>Recipe ID</th><th>本地可用</th><th>指纹</th></tr>
        <tr v-for="(r, i) in asset.resources" :key="i">
          <td>{{ subTypeLabel(r.rsubtype) }}</td>
          <td class="mono" :title="r.rsubtype">{{ r.rsubtype.slice(0, 40) }}{{ r.rsubtype.length > 40 ? '…' : '' }}</td>
          <td>{{ fmtBytes(r.rlen) }}</td>
          <td class="mono">
            <span v-if="r.rfileid === '-1'" style="color:#9ca3af">仅云端</span>
            <template v-else>{{ r.rfileid }}</template>
          </td>
          <td class="mono" :title="r.rrecipe">{{ r.rrecipe.slice(0, 28) }}{{ r.rrecipe.length > 28 ? '…' : '' }}</td>
          <td>{{ r.ravail }}</td>
          <td class="mono" :title="r.rfp">{{ r.rfp.length > 14 ? r.rfp.slice(0, 14) + '…' : r.rfp }}</td>
        </tr>
      </table>
    </template>

    <RawColumns :state="state" :asset="asset" />
  </div>
</template>
