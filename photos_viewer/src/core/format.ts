/* ============ 语义美化（展示用，不改变原始值） ============ */
import type { Asset } from './aggregate';

export function cleanV(v: unknown): string {
  return String(v === undefined || v === null ? '' : v).replace(/\u200e/g, '');
}

const IMPORT_MAP: Record<number, string> = {
  0: '云/其他', 1: '后置摄像头', 2: '前置摄像头', 3: '第三方App', 4: 'PhotoBooth',
  5: 'PhotoBooth', 6: '第三方App', 7: 'iCloud分享链接', 8: '系统App', 9: '原生App',
  10: '测试', 11: '测试', 12: 'SWY联动',
};
export function importLabel(v: string): string {
  const n = parseInt(v, 10);
  if (isNaN(n)) return cleanV(v);
  return IMPORT_MAP[n] || cleanV(v);
}

export function subTypeLabel(v: string): string {
  const s = cleanV(v);
  if (/Orig-Size/i.test(s)) return '原始文件';
  if (/Large-Thumb/i.test(s)) return '大缩略图';
  if (/Med-Thumb/i.test(s)) return '中缩略图';
  if (/Small-Thumb/i.test(s)) return '小缩略图';
  if (/Video-Med/i.test(s)) return '中等视频档';
  if (/Video-Small/i.test(s)) return '小视频档';
  if (/Adjust-Mutation|with-Adjustments/i.test(s)) return '编辑/调整数据';
  if (/MOV-Optimized|Optimized/i.test(s)) return '优化视频档';
  if (/Large-Thumb|Large/i.test(s)) return '大图';
  if (s === '') return '(空)';
  return s;
}

export function fmtBytes(v: string): string {
  const n = parseFloat(v);
  if (!isFinite(n) || n < 0) return '';
  if (n >= 1048576) return (n / 1048576).toFixed(2) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

export function fmtDur(v: string): string {
  const n = parseFloat(v);
  if (!isFinite(n) || n <= 0) return '';
  if (n < 60) return n.toFixed(1) + ' 秒';
  const mm = Math.floor(n / 60), ss = Math.round(n % 60);
  return mm + '分' + String(ss).padStart(2, '0') + '秒';
}

export function kindLabel(f: Record<string, string>): string {
  const kv = (f.kind || '').toLowerCase();
  const sv = (f.kindSub || '');
  let base = kv.includes('video') || kv.startsWith('1') ? '视频' : '照片';
  if (/Screenshot/i.test(sv)) base += '·截图';
  else if (/Live-Photo/i.test(sv)) base += '·Live';
  else if (/Slow-Mo/i.test(sv)) base += '·慢动作';
  else if (/Time-lapse/i.test(sv)) base += '·延时';
  else if (/Screen_Recording/i.test(sv)) base += '·录屏';
  return base;
}

export function frontBackLabel(v: string): string {
  const s = cleanV(v);
  if (/^1|Front/i.test(s)) return '前置';
  if (/^0|Back/i.test(s)) return '后置';
  return s;
}

export function flashLabel(v: string): string {
  const s = cleanV(v);
  if (/^1|Fired/i.test(s)) return '开启';
  if (/^0|No Flash/i.test(s)) return '关闭';
  return s;
}

/** 字段展示值：与详情面板一致的语义美化（设备/来源等字段转为中文标签），分类拼接列共用 */
export function fieldDisplay(key: string, v: string): string {
  switch (key) {
    case 'importedBy': return importLabel(v);
    case 'frontBack': return frontBackLabel(v);
    case 'flash': return flashLabel(v);
    case 'fileSize': return fmtBytes(v) + (parseFloat(v) ? ' (' + v + ' B)' : '');
    case 'duration': return fmtDur(v);
    default: return v;
  }
}

export function isBlobCol(name: string): boolean {
  return /HEX|Data\/|DataStoreKey|Fingerprint|Data$/i.test(name) || false;
}
export function looksPlist(v: string): boolean {
  try {
    const bin = atob(String(v).slice(0, 16));
    return bin.slice(0, 8) === 'bplist00';
  } catch { return false; }
}

/* ---- 时间处理：库内时间戳均为 UTC；"当地" = UTC + 记录自带时区偏移 ---- */
function pad2(n: number): string { return String(n).padStart(2, '0'); }

export function sqliteUtcPlus(utcStr: string, addSec: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/.exec(String(utcStr || '').trim());
  if (!m) return '';
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) + (addSec || 0) * 1000);
  return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()) +
         ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + ':' + pad2(d.getUTCSeconds());
}

export function tzLabel(sec: string | number): string {
  const s = parseInt(String(sec), 10);
  if (!isFinite(s)) return '';
  return (s < 0 ? '-' : '+') + pad2(Math.floor(Math.abs(s) / 3600)) + ':' + pad2(Math.floor(Math.abs(s) % 3600 / 60));
}

export function tzOffSeconds(f: Record<string, string>): number | null {
  const raw = cleanV(f.tzoffset);
  if (raw === '') return null;
  const s = parseInt(raw, 10);
  return isFinite(s) ? s : null;
}

/* ---- 主表行级展示值（来源/GPS 摘要） ---- */
export function srcLabel(a: Asset): string {
  const f = a.f;
  const imp = importLabel(f.importedBy);
  const who = cleanV(f.importName) || (cleanV(f.bundleId) || '').replace(/\u200e/g, '');
  const short = who.replace(/^.*\.([^.]+)$/, '$1');
  return who ? imp + ' · ' + short : imp;
}

export function gpsParts(f: Record<string, string>): { lat: number; lon: number } | null {
  const lat = parseFloat(f.lat), lon = parseFloat(f.lon);
  if (isFinite(lat) && isFinite(lon) && lat !== -180 && lon !== -180) return { lat, lon };
  return null;
}
export function gpsText(f: Record<string, string>): string {
  const p = gpsParts(f);
  return p ? p.lat.toFixed(5) + ', ' + p.lon.toFixed(5) : '';
}
