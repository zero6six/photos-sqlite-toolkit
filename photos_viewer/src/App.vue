<script setup lang="ts">
import { onMounted, ref } from 'vue';
import StatsBar from './components/StatsBar.vue';
import ControlsBar from './components/ControlsBar.vue';
import AssetTable from './components/AssetTable.vue';
import Dropzone from './components/Dropzone.vue';
import { dataState, errMsg, toastMsg } from './state';
import { loadCSVText, readFile } from './composables/useCsvLoad';

const fileInput = ref<HTMLInputElement | null>(null);
const dragging = ref(false);

function pickFile(): void { fileInput.value?.click(); }
function onFileChange(e: Event): void {
  const t = e.target as HTMLInputElement;
  if (t.files && t.files[0]) readFile(t.files[0]);
  t.value = '';
}

/* sticky 表头偏移跟随筛选栏实际高度，避免表头钻到筛选栏下 */
function syncStickyHeader(): void {
  const c = document.querySelector('#controls') as HTMLElement | null;
  document.documentElement.style.setProperty('--ctrl-h', ((c && c.offsetHeight) || 47) + 'px');
}

onMounted(() => {
  /* 测试钩子：允许无文件对话框注入 CSV 文本 */
  (window as unknown as Record<string, unknown>).__loadCSVText = loadCSVText;

  document.addEventListener('dragover', e => { e.preventDefault(); dragging.value = true; });
  document.addEventListener('dragleave', e => { if (e.relatedTarget === null) dragging.value = false; });
  document.addEventListener('drop', e => {
    e.preventDefault(); dragging.value = false;
    const f = e.dataTransfer?.files?.[0];
    if (f) readFile(f);
  });

  const c = document.querySelector('#controls');
  if (c) new ResizeObserver(syncStickyHeader).observe(c);
  window.addEventListener('resize', syncStickyHeader);
});
</script>

<template>
  <header>
    <h1>📷 iOS 相册取证导出查看器</h1>
    <span class="hint">加载 Photos.sqlite 查询导出的 CSV · 全程本地解析，无网络请求</span>
    <button v-show="dataState" class="btn" @click="pickFile">载入其他文件</button>
  </header>

  <div id="stats" :style="dataState ? 'display:flex' : ''"><StatsBar v-if="dataState" :state="dataState" /></div>
  <div id="controls" :style="dataState ? 'display:flex' : ''"><ControlsBar v-if="dataState" :state="dataState" /></div>

  <main id="main" :style="dataState ? '' : 'display:none'">
    <div id="tableWrap"><AssetTable v-if="dataState" :state="dataState" /></div>
  </main>

  <Dropzone v-show="!dataState" @pick="pickFile" />
  <div id="overlay" :style="dragging ? 'display:flex' : ''">松开以载入 CSV</div>
  <div id="err" :style="errMsg ? 'display:block' : ''">{{ errMsg }}</div>
  <div id="toast" :style="toastMsg ? 'display:block' : ''">{{ toastMsg }}</div>
  <input type="file" id="file" accept=".csv,text/csv" hidden ref="fileInput" @change="onFileChange">
</template>
