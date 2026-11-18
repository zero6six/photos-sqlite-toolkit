<script setup lang="ts">
defineEmits<{ pick: [] }>();
</script>

<template>
  <div id="dropzone">
    <div class="big">🗂️</div>
    <div>把查询导出的 CSV 文件拖到这里，或 <span class="pick" @click="$emit('pick')">点击选择文件</span></div>
    <note>适配 ScottKjr 仓库（iOS11~17）与 photos_sqlite_export（iOS11~26）两代查询的导出格式：
          列按名称模糊匹配，缺失的列自动隐藏、多出的列可在行详情"全部原始列"中查看；
          同一照片的缩略图/视频衍生行会自动折叠。</note>
  </div>
</template>
