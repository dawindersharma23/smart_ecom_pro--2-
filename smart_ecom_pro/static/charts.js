/* Tiny dependency-free SVG/CSS chart helpers (works offline). */
(function (root) {
  const PAL = ['#5b5bf0', '#1b8a3a', '#c0392b', '#e67e22', '#8e44ad', '#16a085', '#7f8c8d'];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const nf = v => Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-IN') : (Math.round(v * 10) / 10);

  function hbars(items, o = {}) {                       // items: [[label, value], ...]
    if (!items || !items.length) return '<small>No data</small>';
    const fmt = o.fmt || nf, mx = Math.max(...items.map(i => i[1]), 1e-9);
    return items.map(([l, v], i) => `<div class="hb"><span class="hl">${esc(l)}</span><div class="ht"><div class="hf" style="width:${Math.max(v / mx * 100, 1)}%;background:${o.colors ? o.colors[i % o.colors.length] : (o.color || PAL[0])}"></div></div><span class="hv">${fmt(v)}</span></div>`).join('');
  }

  function donut(data, o = {}) {                        // data: {label: value}
    const colors = o.colors || {}, e = Object.entries(data || {}).filter(([, v]) => v > 0), tot = e.reduce((a, [, v]) => a + v, 0);
    if (!tot) return '<small>No data</small>';
    const r = 50, c = 2 * Math.PI * r; let off = 0;
    const col = (k, i) => colors[k] || PAL[i % PAL.length];
    const arcs = e.map(([k, v], i) => { const len = v / tot * c; const s = `<circle cx="60" cy="60" r="${r}" fill="none" stroke="${col(k, i)}" stroke-width="22" stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 60 60)"/>`; off += len; return s; }).join('');
    const leg = e.map(([k, v], i) => `<div><i style="background:${col(k, i)}"></i>${esc(k)}: ${v} (${Math.round(v / tot * 100)}%)</div>`).join('');
    return `<div class="dn"><svg viewBox="0 0 120 120" width="${o.size || 150}" height="${o.size || 150}">${arcs}<text x="60" y="65" text-anchor="middle" font-size="16" font-weight="bold">${tot}</text></svg><div class="lg">${leg}</div></div>`;
  }

  function stack(data, colors) {                        // data: {aspect: {Positive:n, Negative:n, Neutral:n}}
    const e = Object.entries(data || {});
    if (!e.length) return '<small>No aspects mentioned</small>';
    const rows = e.map(([a, d]) => {
      const t = (d.Positive || 0) + (d.Negative || 0) + (d.Neutral || 0) || 1;
      const seg = ['Positive', 'Neutral', 'Negative'].map(k => d[k] ? `<div title="${k}: ${d[k]}" style="width:${d[k] / t * 100}%;background:${colors[k]}"></div>` : '').join('');
      return `<div class="hb"><span class="hl">${esc(a)}</span><div class="ht stk">${seg}</div><span class="hv">${t}</span></div>`;
    }).join('');
    return rows + '<div class="lg2">' + ['Positive', 'Neutral', 'Negative'].map(k => `<span><i style="background:${colors[k]}"></i>${k}</span>`).join('') + '</div>';
  }

  function line(series, o = {}) {                       // series: [{name, xs, ys, color, dash}]
    const all = (series || []).filter(s => s.ys && s.ys.length), marks = o.marks || [];
    if (!all.length) return '<small>No data</small>';
    const w = o.w || 560, h = o.h || 240, fmt = o.fmt || nf;
    const xs = all.flatMap(s => s.xs).concat(marks.map(m => m.x)), ys = all.flatMap(s => s.ys).concat(marks.map(m => m.y));
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (x1 === x0) x1 = x0 + 1; if (y1 === y0) y1 = y0 + 1;
    const pad = (y1 - y0) * .08; const nonNeg = Math.min(...ys) >= 0; y0 -= pad; y1 += pad; if (nonNeg && y0 < 0) y0 = 0;
    const L = 56, R = 14, T = 12, B = 34, X = x => L + (x - x0) / (x1 - x0) * (w - L - R), Y = y => h - B - (y - y0) / (y1 - y0) * (h - T - B);
    let g = '';
    for (let i = 0; i <= 4; i++) { const v = y0 + (y1 - y0) * i / 4, yy = Y(v).toFixed(1); g += `<line x1="${L}" x2="${w - R}" y1="${yy}" y2="${yy}" stroke="#e6e6ef"/><text x="${L - 6}" y="${(+yy + 4)}" text-anchor="end" font-size="10" fill="#666">${fmt(v)}</text>`; }
    for (let i = 0; i <= 4; i++) { const v = x0 + (x1 - x0) * i / 4; g += `<text x="${X(v).toFixed(1)}" y="${h - B + 14}" text-anchor="middle" font-size="10" fill="#666">${fmt(v)}</text>`; }
    const lines = all.map((s, i) => `<polyline fill="none" stroke="${s.color || PAL[i % PAL.length]}" stroke-width="2" ${s.dash ? 'stroke-dasharray="6 4"' : ''} points="${s.xs.map((x, j) => X(x).toFixed(1) + ',' + Y(s.ys[j]).toFixed(1)).join(' ')}"/>`).join('');
    const mk = marks.map(m => `<circle cx="${X(m.x).toFixed(1)}" cy="${Y(m.y).toFixed(1)}" r="5" fill="#c0392b"/><text x="${Math.min(X(m.x) + 8, w - 110).toFixed(1)}" y="${(Y(m.y) - 8).toFixed(1)}" font-size="11" fill="#c0392b">${esc(m.label)}</text>`).join('');
    const leg = all.map((s, i) => `<span><i style="background:${s.color || PAL[i % PAL.length]}"></i>${esc(s.name)}</span>`).join('');
    return `<div class="ch"><svg viewBox="0 0 ${w} ${h}" width="100%">${g}${lines}${mk}<text x="${w / 2}" y="${h - 4}" text-anchor="middle" font-size="11" fill="#444">${esc(o.xlabel || '')}</text><text x="12" y="${h / 2}" font-size="11" fill="#444" text-anchor="middle" transform="rotate(-90 12 ${h / 2})">${esc(o.ylabel || '')}</text></svg><div class="lg2">${leg}</div></div>`;
  }

  function scatter(pts, o = {}) {                       // pts: [[x, y], ...] with a y = x reference line
    if (!pts || !pts.length) return '<small>No data</small>';
    const w = 420, h = 280, L = 56, R = 12, T = 12, B = 34, mx = Math.max(...pts.flat(), 1), X = v => L + v / mx * (w - L - R), Y = v => h - B - v / mx * (h - T - B);
    let g = '';
    for (let i = 0; i <= 4; i++) { const v = mx * i / 4; g += `<line x1="${L}" x2="${w - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="#e6e6ef"/><text x="${L - 6}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end" font-size="10" fill="#666">${nf(v)}</text><text x="${X(v).toFixed(1)}" y="${h - B + 14}" text-anchor="middle" font-size="10" fill="#666">${nf(v)}</text>`; }
    const dots = pts.map(([a, b]) => `<circle cx="${X(a).toFixed(1)}" cy="${Y(b).toFixed(1)}" r="2.5" fill="#5b5bf0" fill-opacity=".55"/>`).join('');
    return `<div class="ch"><svg viewBox="0 0 ${w} ${h}" width="100%">${g}<line x1="${X(0)}" y1="${Y(0)}" x2="${X(mx)}" y2="${Y(mx)}" stroke="#c0392b" stroke-dasharray="5 4"/>${dots}<text x="${w / 2}" y="${h - 4}" text-anchor="middle" font-size="11" fill="#444">${esc(o.xlabel || '')}</text><text x="12" y="${h / 2}" font-size="11" fill="#444" text-anchor="middle" transform="rotate(-90 12 ${h / 2})">${esc(o.ylabel || '')}</text></svg><div class="lg2"><span>Dashed line = perfect prediction</span></div></div>`;
  }

  function diverge(items) {                              // items: [[label, value in -1..1]]  (red = negative, green = positive)
    if (!items || !items.length) return '<small>No aspects mentioned</small>';
    return items.map(([l, v]) => { const w = Math.min(Math.abs(v), 1) * 50, left = v >= 0 ? 50 : 50 - w;
      return `<div class="hb"><span class="hl">${esc(l)}</span><div class="ht dv"><i class="mid"></i><div class="hf" style="position:absolute;left:${left}%;width:${w}%;background:${v >= 0 ? '#1b8a3a' : '#c0392b'}"></div></div><span class="hv">${v > 0 ? '+' : ''}${v.toFixed(2)}</span></div>`; }).join('');
  }

  const api = { diverge, hbars, donut, stack, line, scatter, esc };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Charts = api;
})(typeof window !== 'undefined' ? window : globalThis);
