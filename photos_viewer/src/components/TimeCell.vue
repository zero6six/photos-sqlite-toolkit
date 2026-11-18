<script setup lang="ts">
import { computed } from 'vue';
import type { AggState } from '../core/aggregate';
import { cleanV, tzOffSeconds, tzLabel, sqliteUtcPlus } from '../core/format';

/* 主表时间单元格：显示当地时间 + 时区标签；悬停给出 UTC 原值、换算依据与来源字段 */
const props = defineProps<{ utcVal: string; f: Record<string, string>; state: AggState; fieldKey: string }>();

const utc = computed(() => cleanV(props.utcVal));
const src = computed(() => props.state.m.rawName[props.fieldKey] || props.fieldKey);
const off = computed(() => tzOffSeconds(props.f));
const local = computed(() => off.value !== null ? sqliteUtcPlus(utc.value, off.value) : '');

const tip = computed(() => off.value !== null
  ? `当地时间 = 库内UTC ${utc.value} + 时区偏移 ${off.value}秒(${cleanV(props.f.tzname) || tzLabel(off.value)})\n` +
    `UTC原值来源字段: ${src.value}`
  : `UTC 时间（该记录无时区偏移字段，未换算当地）\n来源字段: ${src.value}`);
</script>

<template>
  <template v-if="utc">
    <template v-if="off !== null">
      <span class="mono" :title="tip">{{ local }}</span><span class="tztag">{{ tzLabel(off) }}</span>
    </template>
    <template v-else>
      <span class="mono" :title="tip">{{ utc }}</span><span class="tztag">UTC</span>
    </template>
  </template>
  <span v-else style="color:#cbd5e1">—</span>
</template>
