/* ============ 2. 列名归一化 + 声明式字段映射 ============ */

export function normCol(name: string): string {
  return String(name)
    .replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, '') // 不可见方向字符
    .toLowerCase()
    .replace(/[.\-_/:()+]+/g, '-')   // 各种分隔符统一为 -
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

/** 逻辑字段定义。pats 按优先级排列：先试全等，再试包含；nots 为排除子串。 */
export interface FieldDef {
  k: string;          // 逻辑字段键
  label: string;      // 展示名
  cat: string;        // 分类（见 CAT_NAMES）
  pats: string[];     // 归一化列名匹配模式
  nots?: string[];    // 包含任一子串则排除
  multi?: boolean;    // 多值字段（相册），聚合时特殊处理
}

export const FIELD_DEFS: FieldDef[] = [
  // 标识
  { k: 'zpk',        label: '主键 zPK',        cat: 'id',    pats: ['zasset-zpk'] },
  { k: 'uuid',       label: '资产 UUID',       cat: 'id',    pats: ['zasset-uuid'] },
  { k: 'filename',   label: '文件名',          cat: 'id',    pats: ['zasset-filename', 'filename'], nots: ['original'] },
  { k: 'origname',   label: '原始文件名',      cat: 'id',    pats: ['zaddassetattr-original-filename', 'original-filename', 'orig-filename'] },
  { k: 'directory',  label: '所在目录',        cat: 'id',    pats: ['zasset-directory'] },
  // 时间（库内为 UTC 时间戳，"当地"行按记录自带时区偏移换算）
  { k: 'dateCreated',label: '拍摄/创建时间(UTC)', cat: 'time', pats: ['zasset-date-created', 'zcldmast-creation-date', 'date-created'] },
  { k: 'dateAdded',  label: '入库(添加)时间(UTC)', cat: 'time', pats: ['zasset-add-date', 'add-date'] },
  { k: 'dateModified',label: '修改时间(UTC)',     cat: 'time',  pats: ['zasset-modification-date', 'modification-date'] },
  { k: 'dateTrashed',label: '移入删除时间(UTC)',  cat: 'time',  pats: ['zasset-trashed-date', 'trashed-date'], nots: ['intresou'] },
  { k: 'exif',       label: 'EXIF时间串(拍摄地墙钟)', cat: 'time', pats: ['exif-string', 'exiftimestamp'] },
  // 来源
  { k: 'importedBy', label: '导入来源',        cat: 'src',   pats: ['zaddassetattr-imported-by', 'zcldmast-imported-by', 'imported-by'],
    nots: ['bundle', 'display', 'session'] },
  { k: 'bundleId',   label: '导入 App Bundle ID', cat: 'src', pats: ['imported-by-bundle-identifier', 'imported-by-bundle-id'] },
  { k: 'importName', label: '导入 App 名称',   cat: 'src',   pats: ['imported-by-display-name'] },
  // 媒体
  { k: 'kind',       label: '种类',            cat: 'media', pats: ['zasset-kind'] },
  { k: 'kindSub',    label: '种类细分',        cat: 'media', pats: ['zasset-kind-sub-type', 'cloud-kind-sub-type', 'kind-sub-type'] },
  { k: 'playback',   label: '播放类型',        cat: 'media', pats: ['playback-style'] },
  { k: 'uti',        label: '文件类型 UTI',    cat: 'media', pats: ['zasset-uniform-type-identifier', 'uniform-type-id', 'compact-uti'] },
  { k: 'duration',   label: '时长(秒)',        cat: 'media', pats: ['zasset-video-duration', 'zextattr-duration', 'duration'],
    nots: ['timescale', 'cp-', 'display', 'bestvideo'] },
  { k: 'fileSize',   label: '原始文件大小',    cat: 'media', pats: ['original-file-size'] },
  // 状态
  { k: 'trashedState',label: '最近删除状态',   cat: 'state', pats: ['zasset-trashed-state', 'trashed-state'],
    nots: ['intresou', 'ptp', 'participant', 'by'] },
  { k: 'hiddenState',label: '隐藏状态',        cat: 'state', pats: ['zasset-hidden'] },
  { k: 'favorite',   label: '收藏',            cat: 'state', pats: ['zasset-favorite'] },
  { k: 'visState',   label: '可见性',          cat: 'state', pats: ['zasset-visibility-state'] },
  { k: 'dupState',   label: '重复项状态',      cat: 'state', pats: ['zasset-duplication-asset-visibility-state', 'duplicate-asset-visibility'] },
  // 位置
  { k: 'lat',        label: '纬度',            cat: 'geo',   pats: ['zasset-latitude', 'zextattr-latitude', 'latitude'] },
  { k: 'lon',        label: '经度',            cat: 'geo',   pats: ['zasset-longitude', 'zextattr-longitude', 'longitude'] },
  { k: 'gpsAcc',     label: 'GPS 精度(米)',    cat: 'geo',   pats: ['gps-horizontal-accuracy'] },
  { k: 'tzname',     label: '时区',            cat: 'geo',   pats: ['time-zone-name'] },
  { k: 'tzoffset',   label: '时区偏移(秒)',    cat: 'geo',   pats: ['zaddassetattr-time-zone-offset', 'time-zone-offset'],
    nots: ['inferred'] },
  // 设备
  { k: 'cameraMake', label: '相机厂商',        cat: 'cam',   pats: ['camera-make'] },
  { k: 'cameraModel',label: '相机型号',        cat: 'cam',   pats: ['camera-model'], nots: ['capture'] },
  { k: 'lens',       label: '镜头型号',        cat: 'cam',   pats: ['lens-model'] },
  { k: 'focal',      label: '焦距(mm)',        cat: 'cam',   pats: ['focal-leng'] },
  { k: 'frontBack',  label: '前/后摄',         cat: 'cam',   pats: ['derived-camera-capture-device', 'camera-captured-device'] },
  { k: 'flash',      label: '闪光灯',          cat: 'cam',   pats: ['flash-fired'] },
  // 相册（parentzgenalbum-* 列名包含 zgenalbum-*，必须排除，否则映射错位）
  { k: 'albumTitle', label: '所属相册',        cat: 'album', pats: ['zgenalbum-title'], nots: ['parent'], multi: true },
  { k: 'albumParent',label: '父级相册/文件夹', cat: 'album', pats: ['parentzgenalbum-title', 'parentzgenalbum'] },
  // 编辑
  { k: 'adjusted',   label: '是否编辑过',      cat: 'edit',  pats: ['zasset-has-adjustments', 'has-adjustments'] },
  { k: 'editorBundle',label: '编辑 App',       cat: 'edit',  pats: ['editor-bundle-id'] },
  { k: 'adjustTs',   label: '编辑时间(UTC)',    cat: 'edit',  pats: ['zasset-adjustment-timestamp', 'adjustment-timestamp'] },
  // 云
  { k: 'cldState',   label: '云端同步状态',    cat: 'cloud', pats: ['zcldmast-cloud-local-state'] },
];

/** 内部资源(ZINTERNALRESOURCE)子表与相册存在性判定的列 */
export interface ResDef { k: string; pats: string[]; nots?: string[] }

export const RES_DEFS: ResDef[] = [
  { k: 'rpk',     pats: ['zintresou-zpk'] },
  { k: 'rsubtype',pats: ['zintresou-datastore-sub-type', 'datastore-sub-type'] },
  { k: 'rtype',   pats: ['zintresou-resource-type', 'resource-type'] },
  { k: 'rrecipe', pats: ['recipe-id'] },
  { k: 'rfileid', pats: ['zintresou-file-id', 'file-id'] },
  { k: 'rlen',    pats: ['data-length'] },
  { k: 'ravail',  pats: ['zintresou-local-availability', 'local-availability'] },
  { k: 'rfp',     pats: ['zintresou-fingerprint', 'fingerprint'], nots: ['master', 'adjusted', 'other', 'similar'] },
];
export const ALBUM_GUID_PATS = ['zgenalbum-cloud-guid'];
export const ALBUM_CREATED_PATS = ['zgenalbum-creation-date'];
export const ALBUM_NOTS = ['parent'];

/** 字段分类展示名与排列顺序（详情面板与分类拼接列共用） */
export const CAT_NAMES: Record<string, string> = {
  id: '标识', time: '时间', src: '来源', media: '媒体', state: '状态',
  geo: '位置', cam: '设备', album: '相册', edit: '编辑', cloud: '云端',
};
export const CAT_ORDER = ['id', 'time', 'src', 'media', 'state', 'geo', 'cam', 'album', 'edit', 'cloud'];

/** 表头 → 逻辑字段/资源字段的映射结果 */
export interface Mapping {
  colsN: string[];                        // 归一化后的表头
  map: Record<string, number>;            // fieldKey -> 列下标
  rawName: Record<string, string>;        // fieldKey -> 原始列名
  resMap: Record<string, number>;         // 资源子表字段 -> 列下标
  albumGuidCol: number;                   // 相册 GUID 列（-1 无）
  albumCreatedCol: number;                // 相册创建时间列（-1 无）
  keyCol: number;                         // 资产键列（-1 无）
  unmapped: number[];                     // 未映射列下标
}

function pickCol(colsN: string[], pats: string[], nots: string[] | undefined, used: Set<number>): number {
  for (const pat of pats) {
    for (let i = 0; i < colsN.length; i++)
      if (!used.has(i) && colsN[i] === pat) return i;
    for (let i = 0; i < colsN.length; i++)
      if (!used.has(i) && colsN[i].includes(pat) && !(nots || []).some(n => colsN[i].includes(n)))
        return i;
  }
  return -1;
}

export function buildMapping(headers: string[]): Mapping {
  const colsN = headers.map(normCol);
  const used = new Set<number>();
  const map: Record<string, number> = {};      // fieldKey -> 列下标
  const rawName: Record<string, string> = {};  // fieldKey -> 原始列名
  for (const def of FIELD_DEFS) {
    const i = pickCol(colsN, def.pats, def.nots, used);
    if (i >= 0) { map[def.k] = i; rawName[def.k] = headers[i]; used.add(i); }
  }
  const resMap: Record<string, number> = {};
  for (const def of RES_DEFS) {
    const i = pickCol(colsN, def.pats, def.nots, used);
    if (i >= 0) { resMap[def.k] = i; used.add(i); }
  }
  const albumGuidCol = pickCol(colsN, ALBUM_GUID_PATS, ALBUM_NOTS, used);
  const albumCreatedCol = pickCol(colsN, ALBUM_CREATED_PATS, ALBUM_NOTS, used);
  // 资产键列：zAsset 的 zPK；退而求其次任意 zPK；再退全行指纹。
  // 连接回显列(别名含'='或master/intresou)不是资产唯一键，必须排除。
  const isEchoCol = (n: string) => n.includes('=') || n.includes('master') || n.includes('intresou');
  let keyCol = -1;
  for (let i = 0; i < colsN.length; i++) if (colsN[i] === 'zasset-zpk') { keyCol = i; break; }
  if (keyCol < 0)
    for (let i = 0; i < colsN.length; i++)
      if (colsN[i].startsWith('zasset') && colsN[i].includes('zpk') && !isEchoCol(colsN[i])) { keyCol = i; break; }
  if (keyCol < 0)
    for (let i = 0; i < colsN.length; i++)
      if (colsN[i].includes('zpk') && !isEchoCol(colsN[i])) { keyCol = i; break; }
  const unmapped = headers.map((_, i) => i).filter(i => !used.has(i));
  return { colsN, map, rawName, resMap, albumGuidCol, albumCreatedCol, keyCol, unmapped };
}
