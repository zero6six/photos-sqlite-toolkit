/* 动态自定义列：取值/排序/去重/空值兜底/分类拼接/持久化回显校验 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { parseCSV } from '../src/core/csv';
import { aggregate, type Asset } from '../src/core/aggregate';
import {
  makeFieldCol, makeRawCol, makeCatCol, colId,
  customValue, catValue, isNumericColumn, sortAssetList,
  isValidCustomColShape, revalidateCustomCols,
} from '../src/composables/customCols';
import { rowValue, sortValue } from '../src/composables/useViewModel';
import { fmtDur } from '../src/core/format';

const HERE = dirname(fileURLToPath(import.meta.url));
const rows = parseCSV(readFileSync(join(HERE, '..', 'test.csv'), 'utf-8'));
const S = aggregate(rows, rows[0]);

describe('列构造与 id', () => {
  it('field/raw/cat 三种列的 id 前缀正确', () => {
    expect(colId(makeFieldCol('cameraModel'))).toBe('field:cameraModel');
    expect(colId(makeRawCol('zExtAttr-Focal Lenght'))).toBe('raw:zExtAttr-Focal Lenght');
    expect(colId(makeCatCol('cam'))).toBe('cat:cam');
  });
  it('label 取自 FIELD_DEFS / CAT_NAMES', () => {
    expect(makeFieldCol('cameraModel').label).toBe('相机型号');
    expect(makeCatCol('cam').label).toBe('设备');
  });
});

describe('customValue 取值', () => {
  it('field 列：SONY 资产相机型号 = ILCE-7M2', () => {
    const sony = S.assets.find(a => a.f.cameraModel === 'ILCE-7M2')!;
    expect(sony).toBeTruthy();
    expect(customValue(S, sony, makeFieldCol('cameraModel'))).toBe('ILCE-7M2');
  });

  it('field 列：无相机型号的资产取值为空串（空值兜底交给展示层）', () => {
    const noCam = S.assets.find(a => a.f.cameraModel === '')!;
    expect(noCam).toBeTruthy();
    expect(customValue(S, noCam, makeFieldCol('cameraModel'))).toBe('');
  });

  it('raw 列：取组内首条非空值（与聚合 firstNonEmpty 语义一致）', () => {
    const name = 'zExtAttr-Focal Lenght';
    const idx = S.headers.indexOf(name);
    expect(idx).toBeGreaterThanOrEqual(0);
    const a = S.assets.find(x => (x.rows[0][idx] || '').trim() === '' && x.rows.some(r => (r[idx] || '').trim() !== ''));
    if (a) {  // 存在"首行空、组内其他行有值"的资产时验证穿透取值
      expect(customValue(S, a, makeRawCol(name))).not.toBe('');
    }
    const a1 = S.assets.find(x => x.f.zpk === '1')!;
    expect(customValue(S, a1, makeRawCol(name))).toBe((a1.rows.find(r => (r[idx] || '').trim() !== '') || [])[idx]?.trim() ?? '');
  });

  it('raw 列：列名不存在于表头时取值为空', () => {
    const a = S.assets[0];
    expect(customValue(S, a, makeRawCol('不存在的列'))).toBe('');
  });
});

describe('分类拼接列（解决"找异类设备"）', () => {
  it('SONY 资产的设备拼接值含厂商与型号', () => {
    const sony = S.assets.find(a => a.f.cameraModel === 'ILCE-7M2')!;
    const v = catValue(S, sony, 'cam');
    expect(v).toContain('SONY');
    expect(v).toContain('ILCE-7M2');
  });

  it('iPhone 11 资产的设备拼接值含 Apple 与型号', () => {
    const ip = S.assets.find(a => a.f.cameraModel === 'iPhone 11')!;
    expect(catValue(S, ip, 'cam')).toContain('Apple · iPhone 11');
  });

  it('语义美化参与拼接：前/后摄转为 前置/后置', () => {
    const a = S.assets.find(x => x.f.frontBack !== '' && x.f.cameraModel !== '');
    if (a) {
      const v = catValue(S, a, 'cam');
      expect(v.includes('前置') || v.includes('后置')).toBe(true);
    }
  });

  it('全空分类拼接值为空串', () => {
    const noCam = S.assets.find(a =>
      a.f.cameraMake === '' && a.f.cameraModel === '' && a.f.lens === '' &&
      a.f.focal === '' && a.f.frontBack === '' && a.f.flash === '');
    if (noCam) expect(catValue(S, noCam, 'cam')).toBe('');
  });

  it('排序后异类设备与多数派分离、空值恒排末尾', () => {
    const col = makeCatCol('cam');
    const sorted = sortAssetList(S.assets, {
      key: colId(col), dir: 1,
      getVal: a => customValue(S, a, col),
      numeric: false,
    });
    const vals = sorted.map(a => customValue(S, a, col));
    const nonEmpty = vals.filter(v => v !== '');
    // 空值全部在尾部
    const firstEmptyIdx = vals.indexOf('');
    if (firstEmptyIdx >= 0) {
      expect(vals.slice(firstEmptyIdx).every(v => v === '')).toBe(true);
    }
    // 非空段有序（localeCompare zh）
    for (let i = 1; i < nonEmpty.length; i++)
      expect(nonEmpty[i - 1].localeCompare(nonEmpty[i], 'zh')).toBeLessThanOrEqual(0);
    // SONY 与 iPhone 14 Pro Max 不与 iPhone 11 混排（各自连续成块）
    const models = sorted.map(a => a.f.cameraModel);
    const blockOf = (m: string) => {
      const idxs = models.map((v, i) => [v, i] as const).filter(([v]) => v === m).map(([, i]) => i);
      return Math.max(...idxs) - Math.min(...idxs) + 1;
    };
    expect(blockOf('iPhone 11')).toBe(models.filter(v => v === 'iPhone 11').length);
    expect(blockOf('ILCE-7M2')).toBe(models.filter(v => v === 'ILCE-7M2').length);
    expect(blockOf('iPhone 14 Pro Max')).toBe(models.filter(v => v === 'iPhone 14 Pro Max').length);
  });
});

describe('排序行为', () => {
  it('isNumericColumn：全数值列判定为数值', () => {
    expect(isNumericColumn(['1', '2.5', ''])).toBe(true);
    expect(isNumericColumn(['a', '1'])).toBe(false);
    expect(isNumericColumn(['', ''])).toBe(false);
    // 带单位/带文字前缀可 parseFloat 的串不算数值列（"2.43 MB"→2.43 的老坑）
    expect(isNumericColumn(['2.43 MB (2542832 B)', '103.4 KB'])).toBe(false);
    expect(isNumericColumn(['45.0 秒', '3分05秒'])).toBe(false);
    expect(isNumericColumn([' 12 ', '+13.5', '-1'])).toBe(true);   // trim + 符号
  });

  /* 按显示串 parseFloat 排序的老 bug：单位倍率丢失、分钟格式截断 */
  const mkAsset = (over: Record<string, string>): Asset =>
    ({ key: 'K' + over.zpk, rows: [], f: { zpk: over.zpk, fileSize: '', duration: '', lat: '', lon: '', ...over },
       albums: [], resources: [], badges: {
         trashed: false, hidden: false, fav: false, edited: false,
         video: false, gps: false, third: false }, searchText: '' });
  const sortLike = (assets: Asset[], key: string, dir: 1 | -1) =>
    sortAssetList(assets, {
      key, dir,
      getVal: a => sortValue(a, key),
      numeric: key === 'sizeLabel' || key === 'durLabel' || key === 'gpsLabel',
    });

  it('大小列按字节数值排：B < KB < MB 跨单位有序', () => {
    const assets = [
      mkAsset({ zpk: '1', fileSize: String(3 * 1048576) }),        // 3 MB
      mkAsset({ zpk: '2', fileSize: '512' }),                      // 512 B
      mkAsset({ zpk: '3', fileSize: String(2.43 * 1048576) }),     // 2.43 MB
      mkAsset({ zpk: '4', fileSize: String(103.4 * 1024) }),       // 103.4 KB
      mkAsset({ zpk: '5', fileSize: '' }),                         // 空
    ];
    const vals = sortLike(assets, 'sizeLabel', 1).map(a => a.f.fileSize);
    expect(vals).toEqual(['512', String(103.4 * 1024), String(2.43 * 1048576), String(3 * 1048576), '']);
    // 降序反转、空值仍恒排尾
    const valsD = sortLike(assets, 'sizeLabel', -1).map(a => a.f.fileSize);
    expect(valsD).toEqual([String(3 * 1048576), String(2.43 * 1048576), String(103.4 * 1024), '512', '']);
  });

  it('时长列按秒排：45 秒 < 3分05秒（显示串会把 3分05秒 当 3）', () => {
    expect(fmtDur('45')).toBe('45.0 秒');
    expect(fmtDur('185')).toContain('3分');                       // 确认显示格式确实是分钟制
    const assets = [mkAsset({ zpk: '1', duration: '185' }), mkAsset({ zpk: '2', duration: '45' })];
    expect(sortLike(assets, 'durLabel', 1).map(a => a.f.duration)).toEqual(['45', '185']);
  });

  it('GPS 列按纬度数值排：9.5 < 27.2，无 GPS 恒排尾', () => {
    const assets = [
      mkAsset({ zpk: '1', lat: '27.28260', lon: '84.16850' }),
      mkAsset({ zpk: '2', lat: '9.5', lon: '100.0' }),
      mkAsset({ zpk: '3', lat: '-33.8688', lon: '151.2093' }),    // 南纬最小
      mkAsset({ zpk: '4', lat: '', lon: '' }),
    ];
    expect(sortLike(assets, 'gpsLabel', 1).map(a => a.f.zpk)).toEqual(['3', '2', '1', '4']);
  });

  it('数值自定义列升序/降序正确且空值恒排尾', () => {
    const col = makeFieldCol('zpk');
    const asc = sortAssetList(S.assets, { key: colId(col), dir: 1, getVal: a => customValue(S, a, col), numeric: true });
    const nums = asc.map(a => parseFloat(a.f.zpk)).filter(n => isFinite(n));
    const sorted = [...nums].sort((x, y) => x - y);
    expect(nums).toEqual(sorted);
    const desc = sortAssetList(S.assets, { key: colId(col), dir: -1, getVal: a => customValue(S, a, col), numeric: true });
    const numsD = desc.map(a => parseFloat(a.f.zpk)).filter(n => isFinite(n));
    expect(numsD).toEqual([...sorted].reverse());
  });

  it('降序时空值仍在末尾', () => {
    const col = makeFieldCol('cameraModel');
    const desc = sortAssetList(S.assets, { key: colId(col), dir: -1, getVal: a => customValue(S, a, col), numeric: false });
    const vals = desc.map(a => customValue(S, a, col));
    const firstEmpty = vals.indexOf('');
    if (firstEmpty >= 0) expect(vals.slice(firstEmpty).every(v => v === '')).toBe(true);
  });

  it('固定列取值与旧版一致（抽样）', () => {
    const a = S.assets.find(x => x.f.zpk === '10')!;
    expect(rowValue(a, 'kindLabel')).toContain('视频');
    expect(rowValue(a, 'gpsLabel')).toBe('27.28260, 84.16850');
  });
});

describe('持久化形状校验与回显', () => {
  it('isValidCustomColShape 过滤非法形状', () => {
    expect(isValidCustomColShape({ kind: 'field', key: 'cameraModel', label: '相机型号' })).toBe(true);
    expect(isValidCustomColShape({ kind: 'hack', key: 'x', label: 'y' })).toBe(false);
    expect(isValidCustomColShape(null)).toBe(false);
    expect(isValidCustomColShape({ kind: 'raw', key: '', label: 'y' })).toBe(false);
  });

  it('revalidateCustomCols：新文件中不存在的列被剔除', () => {
    const cols = [
      makeFieldCol('cameraModel'),                       // 存在
      makeFieldCol('no-such-field'),                     // 逻辑字段不存在
      makeRawCol('zExtAttr-Focal Lenght'),               // 原始列存在
      makeRawCol('不存在的列'),                           // 原始列不存在
      makeCatCol('cam'),                                 // 分类有映射字段
      makeCatCol('album'),                               // 分类有映射字段（相册）
    ];
    const valid = revalidateCustomCols(cols, S).map(colId);
    expect(valid).toEqual(['field:cameraModel', 'raw:zExtAttr-Focal Lenght', 'cat:cam', 'cat:album']);
  });

  it('revalidateCustomCols：删掉设备列的变体 CSV 中 cat:cam 被剔除', () => {
    const camIdxs = S.headers.map((h, i) => [h, i] as const)
      .filter(([h]) => /camera|lens|focal|flash/i.test(h)).map(([, i]) => i);
    const headers = S.headers.filter((_, i) => !camIdxs.includes(i));
    const dataRows = rows.slice(1).map(r => r.filter((_, i) => !camIdxs.includes(i)));
    const S2 = aggregate([headers, ...dataRows], headers);
    const valid = revalidateCustomCols([makeCatCol('cam'), makeFieldCol('cameraModel')], S2);
    expect(valid.map(colId)).toEqual([]);
  });
});

describe('从无值资产添加列的场景（根因修复验证）', () => {
  it('无相机型号的资产也能构造 cameraModel 列并提取其他资产的同字段值', () => {
    // 模拟：用户展开一个设备信息为空的行，勾选模式后点击"相机型号"（空字段也显示）
    const noCam = S.assets.find(a =>
      a.f.cameraModel === '' && a.f.cameraMake === '' && a.f.frontBack !== '') as Asset | undefined;
    expect(noCam).toBeTruthy();
    const col = makeFieldCol('cameraModel');           // 不依赖 noCam 的值即可创建
    const values = S.assets.map(a => customValue(S, a, col));
    expect(values.filter(v => v !== '').length).toBe(72); // 72/92 个资产有相机型号
  });
});
