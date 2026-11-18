<script setup lang="ts">
import type { Badges as BadgesT } from '../core/aggregate';
defineProps<{ b: BadgesT }>();
</script>

<template>
  <span v-if="b.trashed" class="badge b-trash">🗑 已删除</span>
  <span v-if="b.hidden" class="badge b-hide">🙈 已隐藏</span>
  <span v-if="b.fav" class="badge b-fav">⭐ 收藏</span>
  <span v-if="b.edited" class="badge b-edit">✏️ 已编辑</span>
  <span v-if="b.gps" class="badge b-gps">📍 GPS</span>
  <span v-if="b.third" class="badge b-app">📱 第三方</span>
  <span v-if="b.video" class="badge b-video">🎬 视频</span>
  <span v-if="!(b.trashed || b.hidden || b.fav || b.edited || b.gps || b.third || b.video)"
        style="color:#cbd5e1">—</span>
</template>
