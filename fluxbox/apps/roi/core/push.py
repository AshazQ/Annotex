"""Optional delivery of the exported JSON to an HTTP endpoint.

Standard library only (urllib), so no extra dependency and no surprises in a
locked-down environment.  Disabled until an endpoint is configured, never
blocks the UI thread, and always reports rather than raises.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

from ..config import APP_VERSION

DEFAULT_TIMEOUT = 15
RETRY_DELAYS = (1.0, 4.0)            # two retries, then give up


class PushResult:
    def __init__(self):
        self.ok = False
        self.status = 0
        self.message = ""
        self.attempts = 0
        self.body = ""

    def summary(self) -> str:
        if self.ok:
            return "Pushed to the endpoint (HTTP %d)" % self.status
        if self.status:
            return "Push failed (HTTP %d): %s" % (self.status, self.message)
        return "Push failed: %s" % (self.message or "unknown error")


def _parse_header(raw):
    """'Authorization: Bearer xyz' -> ('Authorization', 'Bearer xyz')."""
    if not raw or ":" not in str(raw):
        return None
    name, _sep, value = str(raw).partition(":")
    name, value = name.strip(), value.strip()
    if not name or not value:
        return None
    return name, value


def validate_url(url) -> tuple:
    """(ok, message).  Refuses anything that is not plain http(s)."""
    url = str(url or "").strip()
    if not url:
        return False, "no endpoint configured"
    if not url.lower().startswith(("http://", "https://")):
        return False, "endpoint must start with http:// or https://"
    if len(url) > 2000:
        return False, "endpoint URL is implausibly long"
    return True, ""


def push_json(url, payload, header: str = "", timeout: int = DEFAULT_TIMEOUT,
              retries: int = len(RETRY_DELAYS), sleep=time.sleep) -> PushResult:
    """POST `payload` as JSON, retrying transient failures.

    4xx responses are not retried - the request itself is wrong, so repeating
    it only wastes the user's time."""
    result = PushResult()
    ok, why = validate_url(url)
    if not ok:
        result.message = why
        return result

    try:
        body = json.dumps(payload).encode("utf-8")
    except Exception as exc:
        result.message = "could not encode the payload: %s" % exc
        return result

    headers = {"Content-Type": "application/json",
               "User-Agent": "ROI-Studio/%s" % APP_VERSION}
    extra = _parse_header(header)
    if extra:
        headers[extra[0]] = extra[1]

    attempts = max(1, int(retries) + 1)
    for attempt in range(attempts):
        result.attempts = attempt + 1
        request = urllib.request.Request(str(url).strip(), data=body,
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=int(timeout)) as resp:
                result.status = int(getattr(resp, "status", 0) or 0)
                result.body = (resp.read(2048) or b"").decode("utf-8", "replace")
                result.ok = 200 <= result.status < 300
                if result.ok:
                    return result
                result.message = "unexpected status"
        except urllib.error.HTTPError as exc:
            result.status = int(exc.code)
            try:
                result.body = (exc.read(2048) or b"").decode("utf-8", "replace")
            except Exception:
                result.body = ""
            result.message = exc.reason or "HTTP error"
            if 400 <= result.status < 500:
                return result                 # our fault - retrying won't help
        except urllib.error.URLError as exc:
            result.message = str(getattr(exc, "reason", exc))
        except Exception as exc:
            result.message = str(exc)

        if attempt < attempts - 1:
            try:
                sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
            except Exception:
                pass
    return result


def build_payload(full_json, roi_map, folder="", note="") -> dict:
    """What gets posted: the full record plus a small delivery envelope."""
    return {
        "source": "ROI Studio",
        "version": APP_VERSION,
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "folder": str(folder),
        "note": str(note or ""),
        "roi_count": full_json.get("roi_count", 0),
        "no_roi_count": full_json.get("no_roi_count", 0),
        "total_polygons": full_json.get("total_polygons", 0),
        "annotations": full_json,
        "roi_map": roi_map,
    }
