/* 组件间契约测试：photos_sqlite_export 产出的 CSV（v0.2.0 起可含 WAL 差分列）→ viewer 核心加载。
 * 检材是入库的合成样本（iOS 26，8 行 × 218 列，5 资产），可随样本再生成同步更新。
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { parseCSV } from '../src/core/csv';
import { aggregate } from '../src/core/aggregate';

const HERE = dirname(fileURLToPath(import.meta.url));
const csvPath = join(HERE, '..', '..', 'photos_sqlite_export', 'samples',
  'Photos_ios26_synthetic_basic.csv');
const rows = parseCSV(readFileSync(csvPath, 'utf-8'));
const S = aggregate(rows, rows[0]);

describe('exporter CSV 契约（samples/Photos_ios26_synthetic_basic.csv）', () => {
  it('8 行 × 218 列', () => {
    expect(rows.length).toBe(9);          // 表头 + 8 数据行
    expect(rows[0].length).toBe(218);
  });

  it('折叠为 5 资产（zPK 1-5，资产1 占 4 行）', () => {
    expect(S.assets.length).toBe(5);
    expect(S.assets.map(a => a.f.zpk).sort()).toEqual(['1', '2', '3', '4', '5']);
    expect(S.assets.find(a => a.f.zpk === '1')!.rows.length).toBe(4);
  });

  it('关键契约字段全部映射（iLEAPP 风格表头）', () => {
    // 曾有缺口：zAsset-Added Date 不被 add-date 模式命中（v0.2.0 修）
    const need = ['zpk', 'uuid', 'filename', 'origname', 'dateCreated', 'dateAdded',
      'dateModified', 'dateTrashed', 'importedBy', 'bundleId', 'kind', 'kindSub',
      'uti', 'fileSize', 'trashedState', 'hiddenState', 'favorite', 'lat', 'lon',
      'cameraMake', 'cameraModel', 'albumTitle'];
    // adjusted 不在列表：iOS 18+ 删除了 ZHASADJUSTMENTS，目录也不导出
    // ZADJUSTMENTSSTATE 列（只用于过滤器 WHERE），该字段在新版 CSV 里天然缺席
    const missing = need.filter(k => S.m.map[k] === undefined);
    expect(missing).toEqual([]);
  });

  it('值抽查：unicode 文件名 / 收藏 / GPS 占位', () => {
    expect(S.assets.find(a => a.f.zpk === '4')!.f.filename)
      .toBe('照片, "测试"\n第二行.jpg');
    expect(S.assets.find(a => a.f.zpk === '1')!.badges.fav).toBe(true);
    expect(S.assets.find(a => a.f.zpk === '3')!.badges.gps).toBe(true);  // 南纬
  });

  it('相册聚合：资产1 两相册 / 资产2 一相册', () => {
    expect(S.assets.find(a => a.f.zpk === '1')!.albums.length).toBe(2);
    expect(S.assets.find(a => a.f.zpk === '2')!.albums.length).toBe(1);
  });

  it('资源折叠：资产1 两条内部资源', () => {
    expect(S.assets.find(a => a.f.zpk === '1')!.resources.length).toBe(2);
  });

  it('旧式 CSV（无 wal 列）不映射 walStatus', () => {
    expect(S.m.map.walStatus).toBeUndefined();
  });
});
