/* 核心逻辑回归测试：由旧 test_core.mjs（从 HTML 抠 CORE 段）移植为直接 import 模块 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { parseCSV } from '../src/core/csv';
import { normCol } from '../src/core/schema';
import { aggregate } from '../src/core/aggregate';
import { subTypeLabel, sqliteUtcPlus, tzLabel, tzOffSeconds } from '../src/core/format';

const HERE = dirname(fileURLToPath(import.meta.url));
const csvPath = join(HERE, '..', 'test.csv');
const rows = parseCSV(readFileSync(csvPath, 'utf-8'));

describe('parseCSV', () => {
  it('410行x219列', () => {
    expect(rows.length).toBe(410);
    expect(rows[0].length).toBe(219);
  });
});

const S = aggregate(rows, rows[0]);

describe('aggregate', () => {
  it('资产数 92', () => expect(S.assets.length).toBe(92));

  const a1 = S.assets.find(a => a.f.zpk === '1');
  it('找到 zPK=1 的资产', () => expect(!!a1).toBe(true));
  it('zPK=1 原始行 6', () => expect(a1!.rows.length).toBe(6));
  it('zPK=1 资源折叠为 3', () => expect(a1!.resources.length).toBe(3));
  it('zPK=1 三类资源标签正确', () => {
    expect(a1!.resources.some(r => subTypeLabel(r.rsubtype) === '原始文件')).toBe(true);
    expect(a1!.resources.some(r => subTypeLabel(r.rsubtype) === '中缩略图')).toBe(true);
    expect(a1!.resources.some(r => subTypeLabel(r.rsubtype) === '小缩略图')).toBe(true);
  });
  it('zPK=1 归属 2 个相册(WhatsApp+未命名)', () => {
    expect(a1!.albums.length).toBe(2);
    expect(a1!.albums.some(x => x.title === 'WhatsApp')).toBe(true);
    expect(a1!.albums.some(x => x.title === '')).toBe(true);
  });
});

describe('badges', () => {
  const cnt = (k: string) => S.assets.filter(a => a.badges[k as keyof typeof a.badges]).length;
  it('已删除资产 1 个=zPK7(7行派生)', () => expect(cnt('trashed')).toBe(1));
  it('隐藏资产 1 个=zPK9', () => expect(cnt('hidden')).toBe(1));
  it('第三方存入 >0', () => expect(cnt('third')).toBeGreaterThan(0));

  const trashedAsset = S.assets.find(a => a.badges.trashed);
  it('zPK=7 已删除, 7 行派生, 删除时间 2025-05-06', () => {
    expect(trashedAsset!.f.zpk).toBe('7');
    expect(trashedAsset!.rows.length).toBe(7);
    expect(/^2025-05-06/.test(trashedAsset!.f.dateTrashed)).toBe(true);
  });

  const a10 = S.assets.find(a => a.f.zpk === '10');
  it('zPK=10 视频且GPS≈27.2826', () => {
    expect(a10!.badges.video).toBe(true);
    expect(a10!.badges.gps).toBe(true);
    expect(Math.abs(parseFloat(a10!.f.lat) - 27.2826)).toBeLessThan(0.01);
  });
  it('zPK=10 资源 6 条', () => expect(a10!.resources.length).toBe(6));
});

describe('时间换算（UTC→当地）', () => {
  it('UTC+8h 换算正确', () => expect(sqliteUtcPlus('2025-04-16 04:45:37', 28800)).toBe('2025-04-16 12:45:37'));
  it('跨日换算正确', () => expect(sqliteUtcPlus('2025-04-16 23:30:00', 7200)).toBe('2025-04-17 01:30:00'));
  it('负偏移(西时区)换算正确', () => expect(sqliteUtcPlus('2025-04-16 01:00:00', -7200)).toBe('2025-04-15 23:00:00'));
  it('时区标签格式正确', () => {
    expect(tzLabel(28800)).toBe('+08:00');
    expect(tzLabel(-12600)).toBe('-03:30');
    expect(tzLabel('')).toBe('');
  });
  it('zPK=1 时区偏移 28800', () => {
    const a1 = S.assets.find(a => a.f.zpk === '1')!;
    expect(tzOffSeconds(a1.f)).toBe(28800);
  });
  it('zPK=1 换算当地与 EXIF串一致', () => {
    const a1 = S.assets.find(a => a.f.zpk === '1')!;
    const exifNorm = a1.f.exif.slice(0, 10).replace(/:/g, '-') + a1.f.exif.slice(10); // 2025:04:16 → 2025-04-16
    expect(sqliteUtcPlus(a1.f.dateCreated, 28800)).toBe(exifNorm);
  });
});

describe('关键字段映射命中', () => {
  it('关键字段全部映射', () => {
    const needFields = ['zpk', 'filename', 'origname', 'dateCreated', 'dateAdded', 'dateModified',
      'dateTrashed', 'importedBy', 'bundleId', 'importName', 'kind', 'kindSub', 'uti', 'fileSize',
      'trashedState', 'hiddenState', 'favorite', 'lat', 'lon', 'cameraModel', 'albumTitle', 'adjusted', 'tzoffset', 'tzname'];
    const missing = needFields.filter(k => S.m.map[k] === undefined);
    expect(missing).toEqual([]);
  });
});

describe('变体CSV：版本容忍', () => {
  const variant = (headers: string[], dataRows: string[][]) => aggregate([headers, ...dataRows], headers);

  it('变体A(iOS17加2列): 92资产/未映射+2', () => {
    const h2 = [...rows[0], 'zMedAnlyAstAttr-ios17 VA Analysis Timestamp', 'zMedAnlyAstAttr-newiOS17 Va Analysis Version'];
    const d2 = rows.slice(1).map(r => [...r, '2025-05-01 10:00:00', '3']);
    const SA = variant(h2, d2);
    expect(SA.assets.length).toBe(92);
    expect(SA.m.unmapped.length).toBe(S.m.unmapped.length + 2);
  });

  it('变体B(删一半列): 92资产', () => {
    const keep = new Set([0, 3]);
    rows[0].forEach((_, i) => { if (i % 2 === 0) keep.add(i); });
    keep.add(rows[0].indexOf('zAsset-Filename'));
    const idx = [...keep].sort((a, b) => a - b);
    const SB = variant(rows[0].filter((_, i) => idx.includes(i)),
      rows.slice(1).map(r => idx.map(i => r[i])));
    expect(SB.assets.length).toBe(92);
  });

  it('变体C(列名大写+乱分隔): 映射仍命中, 92资产', () => {
    const h3 = rows[0].map(h => h.toUpperCase().replace(/-/g, ' . '));
    const SC = variant(h3, rows.slice(1));
    expect(SC.m.map.filename).toBeDefined();
    expect(SC.m.map.dateCreated).toBeDefined();
    expect(SC.assets.length).toBe(92);
  });

  it('变体D(无zAsset-zPK,回退其他zpk列): 92资产', () => {
    const zi = rows[0].indexOf('zAsset-zPK');
    const h4 = rows[0].filter((_, i) => i !== zi);
    const SD = variant(h4, rows.slice(1).map(r => r.filter((_, i) => i !== zi)));
    expect(SD.assets.length).toBe(92);
  });

  it('变体E(无任何zpk列): 整行去重=409, 不抛异常', () => {
    const keep: number[] = [];
    rows[0].forEach((h, i) => { if (!/zpk/i.test(normCol(h))) keep.push(i); });
    const SE = variant(rows[0].filter((_, i) => keep.includes(i)),
      rows.slice(1).map(r => keep.map(i => r[i])));
    expect(SE.assets.length).toBe(409);
  });
});
