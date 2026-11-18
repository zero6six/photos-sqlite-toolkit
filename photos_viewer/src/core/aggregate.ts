/* ============ 3. 资产聚合 ============ */
import { buildMapping, FIELD_DEFS, RES_DEFS, type Mapping } from './schema';

export interface Album { title: string; guid: string; created: string }
export type ResourceRec = Record<string, string>;
export interface Badges {
  trashed: boolean; hidden: boolean; fav: boolean; edited: boolean;
  video: boolean; gps: boolean; third: boolean;
}
export interface Asset {
  key: string;                        // 分组键（展示/展开状态跟踪用）
  rows: string[][];                   // 组内全部原始行
  f: Record<string, string>;          // 逻辑字段值（fieldKey -> 值）
  albums: Album[];
  resources: ResourceRec[];
  badges: Badges;
  searchText: string;                 // 搜索用小写拼接文本
}
export interface AggState {
  headers: string[];
  m: Mapping;
  assets: Asset[];
  fileName?: string;
}

const IMPORT_MAP: Record<number, string> = {
  0: '云/其他', 1: '后置摄像头', 2: '前置摄像头', 3: '第三方App', 4: 'PhotoBooth',
  5: 'PhotoBooth', 6: '第三方App', 7: 'iCloud分享链接', 8: '系统App', 9: '原生App',
  10: '测试', 11: '测试', 12: 'SWY联动',
};
export function importSourceLabel(n: number): string { return IMPORT_MAP[n] || ''; }

export function firstNonEmpty(rows: string[][], idx: number): string {
  for (const r of rows) { const v = (r[idx] || '').trim(); if (v !== '') return r[idx]; }
  return '';
}
export function isOne(v: string): boolean { return /^\s*1[-!]/.test(v || ''); }  // '1-Asset In Trash…-1'

/** 将 CSV 行按资产键（zAsset-zPK）分组聚合为资产列表 */
export function aggregate(rows: string[][], headers: string[]): AggState {
  const m = buildMapping(headers);
  const dataRows = rows.slice(1);
  const groups = new Map<string, string[][]>();
  for (let ri = 0; ri < dataRows.length; ri++) {
    const r = dataRows[ri];
    let key: string;
    if (m.keyCol >= 0 && String(r[m.keyCol] || '').trim() !== '') key = 'K' + r[m.keyCol];
    else if (m.keyCol >= 0) key = 'E' + ri;      // 键列为空：按行独立成组，避免无关资产被并组
    else key = 'R' + JSON.stringify(r);          // 无键列：按整行去重
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(r);
  }
  const assets: Asset[] = [];
  for (const [key, grows] of groups) {
    const f: Record<string, string> = {};
    for (const def of FIELD_DEFS)
      if (m.map[def.k] !== undefined) f[def.k] = def.multi ? '' : firstNonEmpty(grows, m.map[def.k]);

    /* 相册（多值）：组内逐行收集，按 标题|GUID 去重 */
    const albums: Album[] = [];
    if (m.map.albumTitle !== undefined) {
      const seen = new Set<string>();
      for (const r of grows) {
        const t = (r[m.map.albumTitle] || '').trim();
        const g = m.albumGuidCol >= 0 ? (r[m.albumGuidCol] || '').trim() : '';
        const c = m.albumCreatedCol >= 0 ? (r[m.albumCreatedCol] || '').trim() : '';
        if (t === '' && g === '' && c === '') continue;      // 该行无相册关联
        const idc = t + '|' + g;
        if (seen.has(idc)) continue;
        seen.add(idc);
        albums.push({ title: t, guid: g, created: c });
      }
      f.albumTitle = albums.map(a => a.title || '(未命名相册)').join('、');
    }

    /* 资源子表：按 zIntResou zPK 去重（消除 资源×相册 笛卡尔积） */
    const resources: ResourceRec[] = [];
    if (m.resMap.rpk !== undefined) {
      const seen = new Set<string>();
      for (const r of grows) {
        const pk = (r[m.resMap.rpk] || '').trim();
        if (pk === '' || seen.has(pk)) continue;
        seen.add(pk);
        resources.push(RES_DEFS.reduce<ResourceRec>((o, d) => {
          if (m.resMap[d.k] !== undefined) o[d.k] = (r[m.resMap[d.k]] || '').trim();
          return o;
        }, {}));
      }
    }

    /* 语义徽章 */
    const latOk = (s: string) => { const n = parseFloat(s); return isFinite(n) && Math.abs(n) <= 90 && n !== -180; };
    const lonOk = (s: string) => { const n = parseFloat(s); return isFinite(n) && Math.abs(n) <= 180 && n !== -180; };
    const hasGPS = latOk(f.lat || '') && lonOk(f.lon || '');
    const impNum = parseInt((f.importedBy || 'x'), 10);
    const bundle = (f.bundleId || '').replace(/\u200e/g, '');
    const thirdParty = [3, 6, 12].includes(impNum) ||
                       (bundle !== '' && !bundle.startsWith('com.apple.'));
    const kindV = (f.kind || '').toLowerCase();
    const badges: Badges = {
      trashed: isOne(f.trashedState), hidden: isOne(f.hiddenState),
      fav: isOne(f.favorite), edited: isOne(f.adjusted),
      video: kindV.includes('video') || kindV.startsWith('1'),
      gps: hasGPS, third: thirdParty,
    };
    const searchText = [
      f.zpk, f.uuid, f.filename, f.origname, f.bundleId, f.importName,
      f.albumTitle, f.importedBy, f.directory,
    ].join(' ').replace(/\u200e/g, '').toLowerCase();

    assets.push({ key, rows: grows, f, albums, resources, badges, searchText });
  }
  return { headers, m, assets };
}
