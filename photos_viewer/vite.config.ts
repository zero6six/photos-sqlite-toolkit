import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { renameSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));

/* 构建产物重命名为 photos_viewer.html：与旧版单文件交付物同名同形态（file:// 直开、零网络请求） */
function renameOutput() {
  return {
    name: 'rename-singlefile-output',
    closeBundle() {
      renameSync(join(root, 'dist/index.html'), join(root, 'dist/photos_viewer.html'));
    },
  };
}

export default defineConfig({
  plugins: [vue(), viteSingleFile(), renameOutput()],
  build: { outDir: 'dist' },
  test: { environment: 'node' },
});
