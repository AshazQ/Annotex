"""The batch report: coverage, summary dashboard and per-image detail.

Writes one self-contained HTML file into the batch folder - no external CSS,
no fonts, no scripts from anywhere else - so it can be mailed, archived or
opened from a share with no network at all.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime

from ..config import APP_VERSION, NDIGITS, REPORT_NAME, SHAPE_TYPES
from . import geometry as geo
from .io_safe import WriteReport, write_text_atomic

# ── palette ───────────────────────────────────────────────────
# Validated with the data-viz palette checker against both surfaces:
# adjacent CVD dE 23.1 light / 19.6 dark, normal-vision 24.0 / 20.9.
# Light-mode aqua sits at 2.74:1, below the 3:1 bar, so every segment
# carries a visible direct label and every chart has a table twin.
C_LIGHT = {
    "page": "#f4f5f7", "surface": "#fcfcfb", "ink": "#0b0b0b",
    "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
    "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)",
    "roi": "#2a78d6", "noroi": "#1baf7a", "todo": "#c3c2b7",
    "bar": "#2a78d6", "good": "#0ca30c", "warn": "#fab219",
}
C_DARK = {
    "page": "#0d0d0d", "surface": "#171a21", "ink": "#ffffff",
    "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
    "axis": "#383835", "border": "rgba(255,255,255,0.10)",
    "roi": "#3987e5", "noroi": "#199e70", "todo": "#383835",
    "bar": "#3987e5", "good": "#0ca30c", "warn": "#fab219",
}

TOP_CAMERAS = 20


def esc(value) -> str:
    return html.escape(str(value), quote=True)


# ══════════════════════════════════════════════════════════════
# ANALYSIS
# ══════════════════════════════════════════════════════════════
def build_stats(rows, image_files=None, folder=""):
    """Everything the report and the in-app dashboard need, as plain data."""
    image_files = list(image_files or [])
    known = set(image_files)

    per_image = {}
    for row in rows:
        name = row.get("image_name", "")
        if not name:
            continue
        polys = geo.parse_multi_polys(row.get("pixel_coords", "")) or \
            geo.parse_multi_polys(row.get("normalized_coords", ""))
        kinds = geo.parse_shape_types(row.get("shape_types", ""), len(polys))
        entry = per_image.setdefault(name, {
            "image_name": name,
            "roi_key": row.get("roi_key", "") or geo.make_roi_key(name),
            "site_id": row.get("site_id", ""),
            "cam_number": row.get("cam_number", ""),
            "polygons": 0, "kinds": [], "status": "todo", "comment": "",
            "width": int(row.get("image_width") or 0),
            "height": int(row.get("image_height") or 0),
            "coverage": 0.0, "in_folder": (not known) or (name in known),
        })
        if row.get("comment"):
            entry["comment"] = row["comment"]
        if row.get("row_type") == "roi" and polys:
            entry["polygons"] += len(polys)
            entry["kinds"].extend(kinds)
            entry["status"] = "roi"
            width = entry["width"] or 0
            height = entry["height"] or 0
            if width and height:
                area = sum(geo.polygon_area(p) for p in polys)
                entry["coverage"] = min(100.0, 100.0 * area / float(width * height))
            elif polys:
                # normalised-only rows still give a fraction of the frame
                norm = geo.parse_multi_polys(row.get("normalized_coords", ""))
                if norm:
                    entry["coverage"] = min(
                        100.0, 100.0 * sum(geo.polygon_area(p) for p in norm))
        elif row.get("row_type") == "no_roi" and entry["status"] == "todo":
            entry["status"] = "no_roi"

    for name in image_files:
        per_image.setdefault(name, {
            "image_name": name, "roi_key": geo.make_roi_key(name),
            "site_id": geo.extract_site_cam(name)[0],
            "cam_number": geo.extract_site_cam(name)[1],
            "polygons": 0, "kinds": [], "status": "todo", "comment": "",
            "width": 0, "height": 0, "coverage": 0.0, "in_folder": True,
        })

    images = sorted(per_image.values(),
                    key=lambda e: geo.natural_key(e["image_name"]))

    # ── per camera ────────────────────────────────────────
    cameras = {}
    for entry in images:
        key = entry["roi_key"] or "(no key)"
        cam = cameras.setdefault(key, {
            "roi_key": key, "site_id": entry["site_id"],
            "cam_number": entry["cam_number"], "images": 0, "annotated": 0,
            "no_roi": 0, "todo": 0, "polygons": 0, "coverage": 0.0,
        })
        cam["images"] += 1
        cam["polygons"] += entry["polygons"]
        cam["coverage"] = max(cam["coverage"], entry["coverage"])
        cam[{"roi": "annotated", "no_roi": "no_roi", "todo": "todo"}[entry["status"]]] += 1
    camera_list = sorted(cameras.values(), key=lambda c: geo.natural_key(c["roi_key"]))

    kind_counts = {k: 0 for k in SHAPE_TYPES}
    for entry in images:
        for kind in entry["kinds"]:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    totals = {
        "images": len(images),
        "annotated": sum(1 for e in images if e["status"] == "roi"),
        "no_roi": sum(1 for e in images if e["status"] == "no_roi"),
        "polygons": sum(e["polygons"] for e in images),
        "cameras": len(camera_list),
        "cameras_covered": sum(1 for c in camera_list if c["polygons"] > 0),
        "cameras_no_roi": sum(1 for c in camera_list
                              if c["polygons"] == 0 and c["no_roi"] > 0),
        "kinds": kind_counts,
        "folder": str(folder),
    }
    totals["remaining"] = max(0, totals["images"] - totals["annotated"]
                              - totals["no_roi"])
    totals["cameras_missing"] = [c["roi_key"] for c in camera_list
                                 if c["polygons"] == 0 and c["no_roi"] == 0]
    totals["mean_coverage"] = (
        sum(e["coverage"] for e in images if e["status"] == "roi")
        / totals["annotated"]) if totals["annotated"] else 0.0
    return {"totals": totals, "images": images, "cameras": camera_list}


# ══════════════════════════════════════════════════════════════
# HTML PIECES
# ══════════════════════════════════════════════════════════════
def _stat_tile(label, value, hint="") -> str:
    return (
        '<div class="tile"><div class="tile-label">%s</div>'
        '<div class="tile-value">%s</div>'
        '<div class="tile-hint">%s</div></div>'
        % (esc(label), esc(value), esc(hint)))


def _progress_bar(totals) -> str:
    """One stacked bar for the three batch outcomes.

    Segments are separated by a 2px surface gap rather than a border, and
    every segment carries a visible label, which is also the relief for the
    light-mode contrast warning on the aqua step."""
    total = max(1, totals["images"])
    parts = [("ROI drawn", totals["annotated"], "roi"),
             ("No ROI", totals["no_roi"], "noroi"),
             ("Remaining", totals["remaining"], "todo")]
    cells = []
    for label, count, slot in parts:
        if count <= 0:
            continue
        pct = 100.0 * count / total
        inside = pct >= 12
        cells.append(
            '<div class="seg seg-%s" style="flex:%.4f 1 0" '
            'title="%s: %d of %d (%.0f%%)">%s</div>'
            % (slot, pct, esc(label), count, total, pct,
               ('<span class="seg-label">%d</span>' % count) if inside else ""))
    legend = "".join(
        '<span class="key"><i class="dot dot-%s"></i>%s <b>%d</b></span>'
        % (slot, esc(label), count) for label, count, slot in parts)
    return ('<div class="bar-wrap"><div class="bar">%s</div>'
            '<div class="legend">%s</div></div>'
            % ("".join(cells) or '<div class="seg seg-todo" style="flex:1"></div>',
               legend))


def _camera_chart(cameras) -> str:
    """Horizontal bars: ROIs per camera.

    One measure, so one hue - never a value ramp across nominal categories.
    Truncated to the busiest cameras; the full set is in the table below."""
    ranked = [c for c in cameras if c["polygons"] > 0]
    ranked.sort(key=lambda c: (-c["polygons"], geo.natural_key(c["roi_key"])))
    shown = ranked[:TOP_CAMERAS]
    if not shown:
        return '<p class="empty">No ROIs have been drawn yet.</p>'

    top = max(c["polygons"] for c in shown)
    rows = []
    for cam in shown:
        pct = 100.0 * cam["polygons"] / float(top)
        rows.append(
            '<div class="brow">'
            '<div class="blabel" title="%s">%s</div>'
            '<div class="btrack"><div class="bfill" style="width:%.2f%%"></div>'
            '<span class="bval">%d</span></div>'
            '</div>'
            % (esc(cam["roi_key"]), esc(cam["roi_key"]), max(pct, 1.2),
               cam["polygons"]))
    note = ""
    if len(ranked) > len(shown):
        note = ('<p class="note">Showing the %d busiest of %d cameras - '
                'the full list is in the coverage table.</p>'
                % (len(shown), len(ranked)))
    return '<div class="bars">%s</div>%s' % ("".join(rows), note)


def _shape_row(kinds) -> str:
    total = sum(kinds.values()) or 0
    if not total:
        return '<p class="empty">No shapes recorded yet.</p>'
    cells = []
    for name in SHAPE_TYPES:
        count = kinds.get(name, 0)
        pct = 100.0 * count / total
        cells.append('<div class="chip"><b>%d</b><span>%s</span>'
                     '<i>%.0f%%</i></div>' % (count, esc(name), pct))
    return '<div class="chips">%s</div>' % "".join(cells)


def _camera_table(cameras) -> str:
    body = []
    for cam in cameras:
        if cam["polygons"] > 0:
            state, cls = "covered", "ok"
        elif cam["no_roi"] > 0:
            state, cls = "marked no_roi", "neutral"
        else:
            state, cls = "not started", "warn"
        body.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%d</td>"
            "<td class='num'>%d</td><td class='num'>%d</td>"
            "<td class='num'>%s</td><td><span class='state %s'>%s</span></td></tr>"
            % (esc(cam["roi_key"]), esc(cam["site_id"]), esc(cam["cam_number"]),
               cam["images"], cam["annotated"], cam["polygons"],
               ("%.1f%%" % cam["coverage"]) if cam["coverage"] else "-",
               cls, esc(state)))
    return ("<table><thead><tr><th>roi_key</th><th>site</th><th>cam</th>"
            "<th class='num'>images</th><th class='num'>annotated</th>"
            "<th class='num'>ROIs</th><th class='num'>frame covered</th>"
            "<th>state</th></tr></thead><tbody>%s</tbody></table>"
            % ("".join(body) or "<tr><td colspan='8'>No cameras found.</td></tr>"))


def _image_table(images) -> str:
    body = []
    labels = {"roi": ("ROI drawn", "ok"), "no_roi": ("No ROI", "neutral"),
              "todo": ("Remaining", "warn")}
    for entry in images:
        text, cls = labels.get(entry["status"], ("?", "neutral"))
        size = ("%d x %d" % (entry["width"], entry["height"])) \
            if entry["width"] and entry["height"] else "-"
        kinds = ", ".join(sorted(set(entry["kinds"]))) if entry["kinds"] else "-"
        body.append(
            "<tr><td class='name'>%s</td><td>%s</td><td>%s</td>"
            "<td class='num'>%d</td><td>%s</td><td class='num'>%s</td>"
            "<td><span class='state %s'>%s</span></td><td>%s</td></tr>"
            % (esc(entry["image_name"]), esc(entry["roi_key"]), size,
               entry["polygons"], esc(kinds),
               ("%.1f%%" % entry["coverage"]) if entry["coverage"] else "-",
               cls, esc(text), esc(entry["comment"] or "")))
    return ("<table><thead><tr><th>image</th><th>roi_key</th><th>size</th>"
            "<th class='num'>ROIs</th><th>shapes</th>"
            "<th class='num'>frame covered</th><th>state</th><th>comment</th>"
            "</tr></thead><tbody>%s</tbody></table>"
            % ("".join(body) or "<tr><td colspan='8'>No images found.</td></tr>"))


def _vars(palette) -> str:
    return "".join("--%s:%s;" % (key, value) for key, value in palette.items())


def _css() -> str:
    # Built by concatenation rather than %-formatting: the stylesheet is full
    # of literal per-cent signs and escaping every one of them is a trap.
    return (
        ":root{color-scheme:light dark;" + _vars(C_LIGHT) + "}"
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
.tile-value{font-size:30px;font-weight:650;margin:4px 0 2px}
.tile-hint{font-size:12px;color:var(--ink2)}
.bar-wrap{margin-top:2px}
.bar{display:flex;gap:2px;height:34px;border-radius:8px;overflow:hidden;
 background:var(--grid)}
.seg{display:flex;align-items:center;justify-content:center;min-width:3px;
 transition:filter .15s}
.seg:hover{filter:brightness(1.08)}
.seg-label{font-size:12px;font-weight:600;color:#fff;
 text-shadow:0 1px 2px rgba(0,0,0,.35)}
.seg-roi{background:var(--roi)}.seg-noroi{background:var(--noroi)}
.seg-todo{background:var(--todo)}
.legend{display:flex;flex-wrap:wrap;gap:18px;margin-top:12px;font-size:13px;
 color:var(--ink2)}
.key{display:flex;align-items:center;gap:7px}
.key b{color:var(--ink);font-variant-numeric:tabular-nums}
.dot{width:11px;height:11px;border-radius:3px;display:inline-block}
.dot-roi{background:var(--roi)}.dot-noroi{background:var(--noroi)}
.dot-todo{background:var(--todo)}
.bars{display:flex;flex-direction:column;gap:7px}
.brow{display:grid;grid-template-columns:170px 1fr;gap:12px;align-items:center;
 min-height:24px}
.blabel{font-size:12px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap}
.btrack{display:flex;align-items:center;gap:8px}
.bfill{height:14px;border-radius:4px;background:var(--bar);transition:filter .15s}
.brow:hover .bfill{filter:brightness(1.12)}
.bval{font-size:12px;font-variant-numeric:tabular-nums;color:var(--ink2)}
.chips{display:flex;flex-wrap:wrap;gap:10px}
.chip{display:flex;align-items:baseline;gap:7px;padding:9px 14px;
 border:1px solid var(--border);border-radius:9px}
.chip b{font-size:19px;font-weight:650}
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
.state.ok{color:var(--roi)}.state.neutral{color:var(--ink2)}
.state.warn{color:var(--warn)}
.scroll{overflow-x:auto}
.note,.empty{color:var(--muted);font-size:12px;margin:12px 0 0}
.missing{display:flex;flex-wrap:wrap;gap:7px;margin-top:4px}
.missing span{font-size:12px;padding:3px 9px;border-radius:6px;
 border:1px solid var(--border);color:var(--ink2);
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
footer{color:var(--muted);font-size:12px;margin-top:26px;text-align:center}
@media print{body{background:#fff;padding:0}.card,.tile{break-inside:avoid}}
"""


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════
def render_html(stats, session=None) -> str:
    totals = stats["totals"]
    folder = totals.get("folder", "")
    name = os.path.basename(str(folder).rstrip(os.sep)) or "batch"
    done_pct = (100.0 * (totals["annotated"] + totals["no_roi"])
                / totals["images"]) if totals["images"] else 0.0

    tiles = "".join([
        _stat_tile("Images", totals["images"], "in this batch"),
        _stat_tile("ROI drawn", totals["annotated"],
                   "%.0f%% of the batch handled" % done_pct),
        _stat_tile("No ROI", totals["no_roi"], "explicitly marked"),
        _stat_tile("Remaining", totals["remaining"], "not yet visited"),
        _stat_tile("Total ROIs", totals["polygons"],
                   "across %d camera(s)" % totals["cameras_covered"]),
        _stat_tile("Mean frame covered",
                   "%.1f%%" % totals["mean_coverage"],
                   "of an annotated image"),
    ])

    missing = totals.get("cameras_missing", [])
    missing_block = ""
    if missing:
        chips = "".join("<span>%s</span>" % esc(k) for k in missing[:200])
        more = ("<p class='note'>and %d more</p>" % (len(missing) - 200)) \
            if len(missing) > 200 else ""
        missing_block = (
            "<section class='card'><h2>Cameras with nothing recorded</h2>"
            "<p class='note' style='margin:0 0 10px'>%d camera(s) have neither "
            "an ROI nor a no_roi decision.</p><div class='missing'>%s</div>%s"
            "</section>" % (len(missing), chips, more))

    session_block = ""
    if session:
        session_block = (
            "<section class='card'><h2>This session</h2><div class='chips'>"
            "<div class='chip'><b>%s</b><span>active time</span></div>"
            "<div class='chip'><b>%d</b><span>images handled</span></div>"
            "<div class='chip'><b>%.0f</b><span>images / hour</span></div>"
            "<div class='chip'><b>%d</b><span>shapes drawn</span></div>"
            "</div></section>"
            % (esc(session.get("elapsed", "-")), int(session.get("images", 0)),
               float(session.get("per_hour", 0.0)), int(session.get("shapes", 0))))

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ROI report - %(name)s</title>
<style>%(css)s</style></head><body><div class="wrap">
<h1>ROI batch report</h1>
<p class="sub"><code>%(folder)s</code><br>Generated %(when)s by ROI Studio v%(version)s</p>
<div class="tiles">%(tiles)s</div>
<section class="card"><h2>Batch progress</h2>%(progress)s</section>
<section class="card"><h2>ROIs per camera</h2>%(chart)s</section>
<section class="card"><h2>Shape mix</h2>%(shapes)s</section>
%(session)s
%(missing)s
<section class="card"><h2>Coverage by camera</h2><div class="scroll">%(cameras)s</div></section>
<section class="card"><h2>Every image</h2><div class="scroll">%(images)s</div></section>
<footer>Coordinates are normalised to %(digits)d decimal places.
Every figure above is also present in %(json)s.</footer>
</div></body></html>
""" % {
        "name": esc(name),
        "css": _css(),
        "folder": esc(folder),
        "when": esc(datetime.now().strftime("%d %b %Y, %H:%M")),
        "version": esc(APP_VERSION),
        "tiles": tiles,
        "progress": _progress_bar(totals),
        "chart": _camera_chart(stats["cameras"]),
        "shapes": _shape_row(totals["kinds"]),
        "session": session_block,
        "missing": missing_block,
        "cameras": _camera_table(stats["cameras"]),
        "images": _image_table(stats["images"]),
        "digits": NDIGITS,
        "json": "roi_annotations.json",
    }


def write_report(rows, folder, image_files=None, session=None,
                 filename: str = REPORT_NAME):
    """Build the stats, render the page and write it atomically.

    Returns (WriteReport, stats) so the caller can reuse the numbers for the
    in-app dashboard without computing them twice."""
    report = WriteReport()
    stats = build_stats(rows, image_files, folder)
    path = os.path.join(str(folder), filename)
    try:
        page = render_html(stats, session)
    except Exception as exc:                         # pragma: no cover
        report.errors.append("could not build the report: %s" % exc)
        return report, stats
    ok, err = write_text_atomic(path, page, keep_backup=False)
    if ok:
        report.written.append(path)
    else:
        report.errors.append("%s: %s" % (filename, err))
    return report, stats


def write_coverage_json(rows, folder, image_files=None,
                        filename: str = "roi_coverage.json"):
    """The same numbers as machine-readable data, for anything downstream."""
    report = WriteReport()
    stats = build_stats(rows, image_files, folder)
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "generator": "ROI Studio v%s" % APP_VERSION,
               "totals": stats["totals"], "cameras": stats["cameras"]}
    path = os.path.join(str(folder), filename)
    ok, err = write_text_atomic(path, json.dumps(payload, indent=1),
                                verify_json=True, keep_backup=False)
    if ok:
        report.written.append(path)
    else:
        report.errors.append("%s: %s" % (filename, err))
    return report, stats
