"""The batch report and the numbers behind the in-app dashboard.  No Qt."""

from __future__ import annotations

import json
import os
from datetime import datetime

from annotex.core import htmlreport as hr
from annotex.core.io_safe import WriteReport, write_text_atomic

from ..config import APP_NAME, APP_VERSION, REPORT_NAME, SUMMARY_NAME

STATUS_TEXT = {"labelled": ("Labelled", "ok"), "background": ("Background", "neutral"),
               "todo": ("Not started", "warn")}


def build_stats(index, rels, project=None, folder=""):
    """Everything the report and the dashboard need, as plain data.

    `index` maps rel -> Summary (or None for an image with no annotation)."""
    images, per_class = [], {}
    formats = {}
    for rel in rels:
        summary = index.get(rel)
        labels = list(summary.labels) if summary else []
        status = summary.status if summary else "todo"
        images.append({"name": rel, "status": status, "boxes": len(labels),
                       "classes": sorted(set(labels)),
                       "verified": bool(summary and summary.verified),
                       "format": summary.fmt if summary else "",
                       "error": summary.error if summary else ""})
        if summary:
            formats[summary.fmt] = formats.get(summary.fmt, 0) + 1
        for label in labels:
            entry = per_class.setdefault(label, {"boxes": 0, "images": set()})
            entry["boxes"] += 1
            entry["images"].add(rel)

    known = {}
    if project is not None:
        for entry in project.sorted_classes():
            known[entry.name] = entry
    names = set(per_class) | {name for name, entry in known.items() if entry.active}
    classes = []
    for name in names:
        usage = per_class.get(name, {"boxes": 0, "images": set()})
        entry = known.get(name)
        classes.append({"name": name,
                        "id": entry.id if entry else None,
                        "colour": entry.color if entry else "",
                        "active": entry.active if entry else True,
                        "in_project": entry is not None,
                        "boxes": usage["boxes"],
                        "images": len(usage["images"])})
    classes.sort(key=lambda c: (-c["boxes"], c["name"].lower()))

    total_boxes = sum(c["boxes"] for c in classes)
    for entry in classes:
        entry["share"] = (100.0 * entry["boxes"] / total_boxes) if total_boxes else 0.0

    totals = {
        "images": len(images),
        "labelled": sum(1 for i in images if i["status"] == "labelled"),
        "background": sum(1 for i in images if i["status"] == "background"),
        "boxes": total_boxes,
        "verified": sum(1 for i in images if i["verified"]),
        "classes_used": sum(1 for c in classes if c["boxes"]),
        "unreadable": sum(1 for i in images if i["error"]),
        "formats": formats,
        "folder": str(folder),
        "project": project.name if project is not None else "",
    }
    totals["annotated"] = totals["labelled"] + totals["background"]
    totals["remaining"] = max(0, totals["images"] - totals["annotated"])
    return {"totals": totals, "images": images, "classes": classes}


def render_html(stats, session=None) -> str:
    totals = stats["totals"]
    folder = totals.get("folder", "")
    name = os.path.basename(str(folder).rstrip(os.sep)) or "batch"
    handled = (100.0 * totals["annotated"] / totals["images"]) if totals["images"] else 0.0

    tiles = "".join([
        hr.stat_tile("Images", totals["images"], "in this batch"),
        hr.stat_tile("Labelled", totals["labelled"],
                     "%.0f%% of the batch handled" % handled),
        hr.stat_tile("Background", totals["background"], "annotated, no boxes"),
        hr.stat_tile("Remaining", totals["remaining"], "no annotation yet"),
        hr.stat_tile("Boxes", totals["boxes"],
                     "across %d class(es)" % totals["classes_used"]),
        hr.stat_tile("Verified", totals["verified"], "marked as checked"),
    ])

    progress = hr.stacked_bar([("Labelled", totals["labelled"], "s1"),
                               ("Background", totals["background"], "s2"),
                               ("Remaining", totals["remaining"], "s3")])
    chart = hr.bar_chart([(c["name"], c["boxes"], c["colour"] or None)
                          for c in stats["classes"]],
                         empty="No boxes have been drawn yet.")

    class_rows = []
    for entry in stats["classes"]:
        if not entry["in_project"]:
            note = hr.state("not in project", "warn")
        elif not entry["active"]:
            note = hr.state("deprecated", "neutral")
        elif entry["boxes"]:
            note = hr.state("in use", "ok")
        else:
            note = hr.state("unused", "neutral")
        class_rows.append([entry["name"],
                           "-" if entry["id"] is None else entry["id"],
                           entry["boxes"], entry["images"],
                           "%.1f%%" % entry["share"], note])
    class_table = hr.table([("class", False), ("id", True), ("boxes", True),
                            ("images", True), ("share", True), ("state", False)],
                           class_rows, "No classes yet.")

    image_rows = []
    for entry in stats["images"]:
        text, kind = STATUS_TEXT.get(entry["status"], ("?", "neutral"))
        if entry["error"]:
            text, kind = "Unreadable", "warn"
        image_rows.append([("raw", "<span class='name'>%s</span>" % hr.esc(entry["name"])),
                           entry["boxes"], ", ".join(entry["classes"]) or "-",
                           "yes" if entry["verified"] else "-",
                           entry["format"] or "-", hr.state(text, kind)])
    image_table = hr.table([("image", False), ("boxes", True), ("classes", False),
                            ("verified", False), ("format", False), ("state", False)],
                           image_rows, "No images found.")

    body = [("<div class='tiles'>%s</div>" % tiles),
            hr.section("Batch progress", progress),
            hr.section("Boxes per class", chart)]
    if session:
        body.append(hr.section("This session", hr.chips([
            (session.get("elapsed", "-"), "active time"),
            (int(session.get("images", 0)), "images handled"),
            ("%.0f" % float(session.get("per_hour", 0.0)), "images / hour"),
            (int(session.get("shapes", 0)), "boxes saved")])))
    body.append(hr.section("Class balance", class_table))
    body.append(hr.section("Every image", image_table))

    subtitle = ("<code>%s</code><br>Class project <b>%s</b> · generated %s by "
                "%s v%s" % (hr.esc(folder), hr.esc(totals.get("project") or "-"),
                            hr.esc(datetime.now().strftime("%d %b %Y, %H:%M")),
                            hr.esc(APP_NAME), hr.esc(APP_VERSION)))
    return hr.page("Labelling report - %s" % name, "Labelling report", subtitle,
                   "\n".join(body),
                   "Every figure above is also present in %s." % SUMMARY_NAME)


def write_report(stats, folder, session=None, filename=REPORT_NAME):
    report = WriteReport()
    path = os.path.join(str(folder), filename)
    try:
        page = render_html(stats, session)
    except Exception as exc:                          # pragma: no cover
        report.errors.append("could not build the report: %s" % exc)
        return report
    ok, err = write_text_atomic(path, page, keep_backup=False)
    if ok:
        report.written.append(path)
    else:
        report.errors.append("%s: %s" % (filename, err))
    return report


def write_summary_json(stats, folder, filename=SUMMARY_NAME):
    report = WriteReport()
    payload = {"generated_at": datetime.now().isoformat(timespec="seconds"),
               "generator": "%s v%s" % (APP_NAME, APP_VERSION),
               "totals": stats["totals"], "classes": stats["classes"]}
    path = os.path.join(str(folder), filename)
    ok, err = write_text_atomic(path, json.dumps(payload, indent=1),
                                verify_json=True, keep_backup=False)
    if ok:
        report.written.append(path)
    else:
        report.errors.append("%s: %s" % (filename, err))
    return report
