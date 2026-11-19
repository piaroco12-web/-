// 사전 브리핑 docx 생성기 (작성: Claude) — 사용법: node build.js jemulpo|chadwick
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, Footer, PageNumber,
} = require('docx');

const { ImageRun } = require('docx');
function jpegSize(buf) { // JPEG SOF 마커에서 크기 읽기
  let i = 2;
  while (i < buf.length) {
    const m = buf[i + 1], len = buf.readUInt16BE(i + 2);
    if (m >= 0xC0 && m <= 0xC3) return { h: buf.readUInt16BE(i + 5), w: buf.readUInt16BE(i + 7) };
    i += 2 + len;
  }
  throw new Error('JPEG size not found');
}
const FONT = '맑은 고딕';
const PAGE_W = 11906, MARGIN = 850; // A4, 약 15mm 여백
const CONTENT_W = PAGE_W - MARGIN * 2;
const NAVY = '1F3864', LIGHT = 'E8EEF7', GRAY = '595959', LINE = 'A6B4CC';

// "**굵게**" 표기를 TextRun 배열로
function runs(text, opt = {}) {
  return String(text).split(/(\*\*[^*]+\*\*)/).filter(Boolean).map(s => {
    const bold = s.startsWith('**');
    return new TextRun({ text: bold ? s.slice(2, -2) : s, bold: bold || opt.bold, size: opt.size || 19, color: opt.color, font: FONT });
  });
}
const para = (text, o = {}) => new Paragraph({ children: runs(text, o), spacing: { before: o.before || 0, after: o.after ?? 40, line: 264 }, alignment: o.align, keepNext: o.keepNext });
const bullet = (text, level = 0) => new Paragraph({ children: runs(text), numbering: { reference: 'b', level }, spacing: { after: 30, line: 260 } });

function heading(text) {
  return new Paragraph({
    children: [new TextRun({ text, bold: true, size: 22, color: NAVY, font: FONT })],
    spacing: { before: 140, after: 60 }, keepNext: true,
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: LINE, space: 2 } },
  });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: LINE };
const borders = { top: border, bottom: border, left: border, right: border };
function cell(text, width, o = {}) {
  const lines = Array.isArray(text) ? text : [text];
  return new TableCell({
    width: { size: width, type: WidthType.DXA }, borders,
    shading: o.fill ? { type: ShadingType.CLEAR, color: 'auto', fill: o.fill } : undefined,
    margins: { top: 40, bottom: 40, left: 90, right: 90 },
    children: lines.map(l => new Paragraph({ children: runs(l, { bold: o.bold, size: o.size || 17 }), spacing: { after: 0, line: 250 }, alignment: o.align })),
  });
}
function table(ratios, header, rows) {
  const sum = ratios.reduce((a, b) => a + b, 0);
  const w = ratios.map(r => Math.floor(CONTENT_W * r / sum));
  w[w.length - 1] += CONTENT_W - w.reduce((a, b) => a + b, 0);
  const tr = [];
  if (header) tr.push(new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, w[i], { fill: LIGHT, bold: true, align: AlignmentType.CENTER })) }));
  rows.forEach(r => tr.push(new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, w[i], header ? {} : (i === 0 ? { fill: LIGHT, bold: true } : {}))) })));
  return [new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: w, rows: tr }), para('', { after: 40 })];
}

function render(spec) {
  const out = [];
  out.push(new Paragraph({ children: [new TextRun({ text: spec.kicker, size: 17, color: GRAY, font: FONT })], spacing: { after: 20 } }));
  out.push(new Paragraph({
    children: [new TextRun({ text: spec.title, bold: true, size: 32, color: NAVY, font: FONT })], spacing: { after: 60 },
    border: { bottom: { style: BorderStyle.THICK, size: 12, color: NAVY, space: 4 } },
  }));
  out.push(para(spec.meta, { size: 17, color: GRAY, after: 100 }));
  for (const b of spec.blocks) {
    if (b.h) out.push(heading(b.h));
    if (b.h3) out.push(new Paragraph({ children: [new TextRun({ text: b.h3, bold: true, size: 20, color: '2F5496', font: FONT })], spacing: { before: 100, after: 40 }, keepNext: true }));
    if (b.p) out.push(para(b.p, { keepNext: String(b.p).startsWith('**') }));
    if (b.note) out.push(para(b.note, { size: 16, color: GRAY }));
    if (b.bullets) b.bullets.forEach(x => Array.isArray(x) ? x.forEach(y => out.push(bullet(y, 1))) : out.push(bullet(x)));
    if (b.kv) out.push(...table([1, 4.2], null, b.kv));
    if (b.table) out.push(...table(b.table.ratios, b.table.header, b.table.rows));
    if (b.photos) {
      // 두 장씩 나란히: [{file, caption}, ...]
      const half = Math.floor(CONTENT_W / 2), PX = 318;
      const nb = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };
      const nbs = { top: nb, bottom: nb, left: nb, right: nb };
      const rows = [];
      for (let i = 0; i < b.photos.length; i += 2) {
        rows.push(new TableRow({ cantSplit: true, children: [0, 1].map(k => {
          const ph = b.photos[i + k];
          if (!ph) return new TableCell({ width: { size: half, type: WidthType.DXA }, borders: nbs, children: [new Paragraph('')] });
          const buf = fs.readFileSync(path.join(__dirname, ph.file));
          const { w, h } = jpegSize(buf);
          const ww = Math.min(PX, Math.round(PX * w / h * 0.75) > PX ? PX : PX), hh = Math.round(ww * h / w);
          const maxH = 260, scale = hh > maxH ? maxH / hh : 1;
          return new TableCell({ width: { size: half, type: WidthType.DXA }, borders: nbs, margins: { top: 40, bottom: 60, left: 60, right: 60 }, children: [
            new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: 'jpg', data: buf, transformation: { width: Math.round(ww * scale), height: Math.round(hh * scale) } })] }),
            new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 30 }, children: runs(ph.caption, { size: 16, color: GRAY }) }),
          ] });
        }) }));
      }
      out.push(new Table({ width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: [half, CONTENT_W - half], rows }), para('', { after: 40 }));
    }
    if (b.questions) b.questions.forEach((q, i) => {
      out.push(new Paragraph({ children: runs(`Q${i + 1}. ${q.q}`, { bold: true }), spacing: { before: 60, after: 20, line: 260 }, keepNext: true }));
      if (q.en) out.push(para(q.en, { size: 17, color: GRAY, after: 20 }));
      out.push(para(`→ 묻는 이유: ${q.why}`, { size: 17, color: GRAY, after: 40 }));
    });
  }
  return new Document({
    creator: 'Claude Code (총괄)', title: spec.title,
    styles: { default: { document: { run: { font: FONT, size: 19 } } } },
    numbering: { config: [{ reference: 'b', levels: [
      { level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 300, hanging: 200 } } } },
      { level: 1, format: LevelFormat.BULLET, text: '–', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 200 } } } },
    ] }] },
    sections: [{
      properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
        new TextRun({ text: `${spec.footer} · `, size: 15, color: GRAY, font: FONT }),
        new TextRun({ children: [PageNumber.CURRENT], size: 15, color: GRAY, font: FONT }),
      ] })] }) },
      children: out,
    }],
  });
}

const name = process.argv[2];
const spec = require(`./${name}.spec.js`);
Packer.toBuffer(render(spec)).then(buf => {
  const file = path.join(__dirname, spec.file);
  fs.writeFileSync(file, buf);
  console.log('wrote', file);
});
