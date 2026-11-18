<script setup lang="ts">
import { computed } from 'vue';
import type { AggState, Badges } from '../core/aggregate';
import { cleanV } from '../core/format';

const props = defineProps<{ state: AggState }>();

const cnt = (k: keyof Badges) => props.state.assets.filter(a => a.badges[k]).length;

const dateSpan = computed(() => {
  const ds = props.state.assets.map(a => cleanV(a.f.dateCreated)).filter(v => v).sort();
  if (!ds.length) return null;
  return { min: ds[0].slice(0, 10), max: ds[ds.length - 1].slice(0, 10) };
});
</script>

<template>
  <span>资产 <b>{{ state.assets.length }}</b> 个（原始 <b>{{ state.assets.reduce((n, a) => n + a.rows.length, 0) }}</b> 行 × <b>{{ state.headers.length }}</b> 列）</span>
  <span>照片 <b>{{ cnt('video') ? state.assets.length - cnt('video') : state.assets.length }}</b> · 视频 <b>{{ cnt('video') }}</b></span>
  <span>已删除 <b>{{ cnt('trashed') }}</b> · 隐藏 <b>{{ cnt('hidden') }}</b> · 收藏 <b>{{ cnt('fav') }}</b> · 含GPS <b>{{ cnt('gps') }}</b> · 第三方存入 <b>{{ cnt('third') }}</b> · 编辑过 <b>{{ cnt('edited') }}</b></span>
  <span v-if="dateSpan">拍摄时间跨度(UTC) <b>{{ dateSpan.min }}</b> ~ <b>{{ dateSpan.max }}</b></span>
  <span class="tz-note">时间说明: 库内时间戳均为UTC；主表已按各记录时区偏移换算为当地时间(角标=偏移)，悬停查看UTC原值与来源字段</span>
  <span v-if="state.fileName" style="margin-left:auto">来源: {{ state.fileName }}</span>
</template>
