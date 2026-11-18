/* ============ 1. CSV 解析（RFC4180） ============ */

/** 解析 CSV 文本为行列数组；行为与旧版单文件实现逐行等价 */
export function parseCSV(text: string): string[][] {
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);   // 去 BOM
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
      else field += c;
    } else {
      if (c === '"') q = true;
      else if (c === ',') { row.push(field); field = ''; }
      else if (c === '\n' || c === '\r') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        row.push(field); rows.push(row); row = []; field = '';
      } else field += c;
    }
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  while (rows.length && rows[rows.length - 1].every(v => v === '')) rows.pop(); // 尾部空行
  return rows;
}
