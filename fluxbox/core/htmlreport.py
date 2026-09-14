"""Pieces for self-contained HTML reports.

Every report the suite writes is one file with its styles inline - no fonts,
scripts or images from anywhere else - so it can be mailed, archived or
opened from a share with no network.  Tools assemble their page from the
helpers here so every report reads as the same product.
"""

from __future__ import annotations

import html

# ── palette ───────────────────────────────────────────────────
# Validated against both surfaces with the data-viz palette checker.  The
# three series slots are the batch outcomes (done, set aside, remaining);
# light-mode s2 sits just under 3:1, so every segment carries a visible direct
# label and every chart has a table twin.
C_LIGHT = {
    "page": "#f4f5f7", "surface": "#fcfcfb", "ink": "#0b0b0b",
    "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
    "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)",
    "s1": "#2a78d6", "s2": "#1baf7a", "s3": "#c3c2b7",
    "bar": "#2a78d6", "good": "#0ca30c", "warn": "#b07a00",
}
C_DARK = {
    "page": "#0d0d0d", "surface": "#171a21", "ink": "#ffffff",
    "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
    "axis": "#383835", "border": "rgba(255,255,255,0.10)",
    "s1": "#3987e5", "s2": "#199e70", "s3": "#383835",
    "bar": "#3987e5", "good": "#0ca30c", "warn": "#fab219",
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def _vars(palette) -> str:
    return "".join("--%s:%s;" % (key, value) for key, value in palette.items())


def css() -> str:
    # Built by concatenation rather than %-formatting: the stylesheet is full
    # of literal per-cent signs and escaping every one of them is a trap.
    return (":root{color-scheme:light dark;" + _vars(C_LIGHT) + "}"
            "@media (prefers-color-scheme:dark){:root{" + _vars(C_DARK) + "}}"
            + _STATIC_CSS)


_STATIC_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:28px 24px 56px;background:var(--page);color:var(--ink);
 font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 14px;letter-spacing:.02em;text-transform:uppercase;
 color:var(--ink2)}
.sub{color:var(--ink2);margin:0 0 22px;font-size:13px}
.sub code{background:transparent;color:var(--ink);word-break:break-all}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
 padding:20px;margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
 margin:0 0 18px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:12px;
 padding:16px}
.tile-label{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
 color:var(--muted)}
.tile-value{font-size:30px;font-weight:650;margin:4px 0 2px;
 font-variant-numeric:tabular-nums}
.tile-hint{font-size:12px;color:var(--ink2)}
.bar{display:flex;gap:2px;height:34px;border-radius:8px;overflow:hidden;
 background:var(--grid)}
.seg{display:flex;align-items:center;justify-content:center;min-width:3px}
.seg:hover{filter:brightness(1.08)}
.seg-label{font-size:12px;font-weight:600;color:#fff;
 text-shadow:0 1px 2px rgba(0,0,0,.35)}
.seg-s1{background:var(--s1)}.seg-s2{background:var(--s2)}.seg-s3{background:var(--s3)}
.legend{display:flex;flex-wrap:wrap;gap:18px;margin-top:12px;font-size:13px;
 color:var(--ink2)}
.key{display:flex;align-items:center;gap:7px}
.key b{color:var(--ink);font-variant-numeric:tabular-nums}
.dot{width:11px;height:11px;border-radius:3px;display:inline-block}
.dot-s1{background:var(--s1)}.dot-s2{background:var(--s2)}.dot-s3{background:var(--s3)}
.bars{display:flex;flex-direction:column;gap:7px}
.brow{display:grid;grid-template-columns:190px 1fr;gap:12px;align-items:center;
 min-height:24px}
.blabel{font-size:12px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;display:flex;align-items:center;gap:7px}
.swatch{width:9px;height:9px;border-radius:2px;flex:none;
 box-shadow:0 0 0 1px var(--border)}
.btrack{display:flex;align-items:center;gap:8px}
.bfill{height:14px;border-radius:4px;background:var(--bar)}
.brow:hover .bfill{filter:brightness(1.12)}
.bval{font-size:12px;font-variant-numeric:tabular-nums;color:var(--ink2)}
.chips{display:flex;flex-wrap:wrap;gap:10px}
.chip{display:flex;align-items:baseline;gap:7px;padding:9px 14px;
 border:1px solid var(--border);border-radius:9px}
.chip b{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums}
.chip span{font-size:13px;color:var(--ink2)}
.chip i{font-size:12px;color:var(--muted);font-style:normal}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--grid);
 vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);
 font-weight:600;border-bottom:1px solid var(--axis)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.name{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
 word-break:break-all}
tbody tr:hover{background:var(--grid)}
.state{font-size:12px;padding:2px 8px;border-radius:20px;white-space:nowrap;
 border:1px solid var(--border)}
.state.ok{color:var(--s1)}.state.neutral{color:var(--ink2)}
.state.warn{color:var(--warn)}
.scroll{overflow-x:auto}
.note,.empty{color:var(--muted);font-size:12px;margin:12px 0 0}
footer{color:var(--muted);font-size:12px;margin-top:26px;text-align:center}
@media print{body{background:#fff;padding:0}.card,.tile{break-inside:avoid}}
"""


# ══════════════════════════════════════════════════════════════
def stat_tile(label, value, hint="") -> str:
    return ('<div class="tile"><div class="tile-label">%s</div>'
            '<div class="tile-value">%s</div>'
            '<div class="tile-hint">%s</div></div>'
            % (esc(label), esc(value), esc(hint)))


def stacked_bar(parts) -> str:
    """One stacked bar.  `parts` is [(label, count, slot)] with slot s1..s3.

    Segments are separated by a 2px gap rather than a border, and every
    segment wide enough carries its count."""
    total = max(1, sum(count for _label, count, _slot in parts))
    cells = []
    for label, count, slot in parts:
        if count <= 0:
            continue
        pct = 100.0 * count / total
        cells.append(
            '<div class="seg seg-%s" style="flex:%.4f 1 0" '
            'title="%s: %d of %d (%.0f%%)">%s</div>'
            % (slot, pct, esc(label), count, total, pct,
               ('<span class="seg-label">%d</span>' % count) if pct >= 12 else ""))
    legend = "".join(
        '<span class="key"><i class="dot dot-%s"></i>%s <b>%d</b></span>'
        % (slot, esc(label), count) for label, count, slot in parts)
    return ('<div><div class="bar">%s</div><div class="legend">%s</div></div>'
            % ("".join(cells) or '<div class="seg seg-s3" style="flex:1"></div>',
               legend))


def bar_chart(rows, empty="Nothing to show yet.", limit=24) -> str:
    """Horizontal bars for one measure, so one hue.

    `rows` is [(label, value, swatch_colour_or_None)].  The swatch marks an
    identity (a class colour the reader knows from the canvas); it never
    encodes the value."""
    ranked = [r for r in rows if r[1] > 0]
    if not ranked:
        return '<p class="empty">%s</p>' % esc(empty)
    shown = ranked[:limit]
    top = max(r[1] for r in shown)
    out = []
    for label, value, swatch in shown:
        pct = 100.0 * value / float(top)
        mark = ('<i class="swatch" style="background:%s"></i>' % esc(swatch)
                if swatch else "")
        out.append('<div class="brow"><div class="blabel" title="%s">%s%s</div>'
                   '<div class="btrack"><div class="bfill" style="width:%.2f%%">'
                   '</div><span class="bval">%d</span></div></div>'
                   % (esc(label), mark, esc(label), max(pct, 1.2), value))
    note = ""
    if len(ranked) > len(shown):
        note = ('<p class="note">Showing the %d largest of %d - the full list '
                'is in the table below.</p>' % (len(shown), len(ranked)))
    return '<div class="bars">%s</div>%s' % ("".join(out), note)


def chips(items) -> str:
    """[(value, caption)] as a row of figure chips."""
    return '<div class="chips">%s</div>' % "".join(
        '<div class="chip"><b>%s</b><span>%s</span></div>'
        % (esc(value), esc(caption)) for value, caption in items)


def table(headers, rows, empty="Nothing to show.") -> str:
    """`headers` is [(text, numeric)]; `rows` are lists of cells.

    A cell is escaped text, or a ("raw", html) pair for markup the caller has
    already escaped."""
    head = "".join('<th%s>%s</th>' % (" class='num'" if numeric else "",
                                      esc(text)) for text, numeric in headers)
    body = []
    for cells in rows:
        tds = []
        for (text, numeric), cell in zip(headers, cells):
            content = cell[1] if isinstance(cell, tuple) and cell[0] == "raw" \
                else esc(cell)
            tds.append("<td%s>%s</td>" % (" class='num'" if numeric else "",
                                          content))
        body.append("<tr>%s</tr>" % "".join(tds))
    if not body:
        body = ["<tr><td colspan='%d'>%s</td></tr>" % (len(headers), esc(empty))]
    return ("<div class='scroll'><table><thead><tr>%s</tr></thead>"
            "<tbody>%s</tbody></table></div>" % (head, "".join(body)))


def state(text, kind="neutral") -> tuple:
    return ("raw", "<span class='state %s'>%s</span>" % (esc(kind), esc(text)))


def section(title, content) -> str:
    return "<section class='card'><h2>%s</h2>%s</section>" % (esc(title), content)


def page(title, heading, subtitle_html, body, footer="") -> str:
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>%s</title>\n<style>%s</style></head><body><div class=\"wrap\">\n"
            "<h1>%s</h1>\n<p class=\"sub\">%s</p>\n%s\n<footer>%s</footer>\n"
            "</div></body></html>\n"
            % (esc(title), css(), esc(heading), subtitle_html, body, footer))
