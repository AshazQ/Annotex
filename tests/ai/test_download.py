"""Downloading a SAM model, against a server on this machine.

The real files are hundreds of megabytes on GitHub, so a tiny local server
stands in for it - one that can be told to ignore resumes, cut a file short
or crawl - and the downloader is driven through everything that goes wrong
on a real connection.  No Qt, no numpy, no onnxruntime needed.

    python tests/ai/test_download.py
"""

import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="annotex_download_")
os.environ["HOME"] = SANDBOX
os.environ["XDG_CONFIG_HOME"] = os.path.join(SANDBOX, "config")

FAILS = []


def ok(label, condition):
    if not condition:
        FAILS.append(label)
    print(("  ok  " if condition else "  XX  ") + label)


class Handler(BaseHTTPRequestHandler):
    files = {}
    honour_range = True
    truncate = 0
    delay = 0.0
    requests = []

    def do_GET(self):
        Handler.requests.append((self.path, self.headers.get("Range")))
        body = Handler.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        start = 0
        wanted = self.headers.get("Range")
        if wanted and Handler.honour_range:
            start = int(wanted.split("=", 1)[1].split("-", 1)[0])
            self.send_response(206)
        else:
            self.send_response(200)
        chunk = body[start:len(body) - Handler.truncate]
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        for index in range(0, len(chunk), 65536):
            self.wfile.write(chunk[index:index + 65536])
            if Handler.delay:
                time.sleep(Handler.delay)

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass                                  # a cancelled client hangs up mid-file


def main():
    from annotex.core.ai import catalog, sam
    from annotex.core.ai.catalog import (CatalogModel, Cancelled, DownloadError,
                                         RemoteFile, download_file, download_model)
    import hashlib

    # ── the catalogue itself ──────────────────────────────
    keys = [model.key for model in catalog.CATALOG]
    ok("every catalogue model has its own key", len(keys) == len(set(keys)) and keys)
    ok("SAM ViT-B comes first, as the default", keys[0] == "sam_vit_b")
    pairs_up = True
    for model in catalog.CATALOG:
        enc, dec = model.encoder.filename, model.decoder.filename
        if not (model.encoder.url.startswith("https://") and model.decoder.url.startswith("https://")
                and model.encoder.size > 0 and model.decoder.size > 0
                and sam._role(enc) == "encoder" and sam._role(dec) == "decoder"
                and sam._family(enc) == sam._family(dec)):
            pairs_up = False
    ok("every download pairs up the way the model folder is read", pairs_up)
    ok("a model is found by its key", catalog.by_key("sam_vit_l").name == "SAM ViT-L")
    ok("an unknown key finds nothing", catalog.by_key("nope") is None)

    named = os.path.join(SANDBOX, "named")
    os.makedirs(named)
    vit_b = catalog.by_key("sam_vit_b")
    for remote in vit_b.files:
        open(os.path.join(named, remote.filename), "wb").close()
    found = [pair for pair in sam.discover_models([named]) if named in pair.encoder]
    ok("a downloaded model is listed by its proper name",
       len(found) == 1 and found[0].name == "SAM ViT-B")
    ok("an empty file is not taken for a downloaded model", not vit_b.installed(named))

    # ── a server to download from ─────────────────────────
    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    encoder_body = os.urandom(3 * 1024 * 1024 + 123)
    decoder_body = os.urandom(200 * 1024 + 7)
    Handler.files = {"/m/tiny.encoder.onnx": encoder_body,
                     "/m/tiny.decoder.onnx": decoder_body}

    def remote(name, body, sha=True):
        return RemoteFile(base + "/m/" + name, len(body),
                          hashlib.sha256(body).hexdigest() if sha else "")

    folder = os.path.join(SANDBOX, "models")

    # a whole download
    seen = []
    dest = os.path.join(folder, "tiny.encoder.onnx")
    download_file(remote("tiny.encoder.onnx", encoder_body), dest,
                  progress=lambda done, total: seen.append((done, total)))
    ok("a file downloads whole", open(dest, "rb").read() == encoder_body)
    ok("and no .part is left behind", not os.path.exists(dest + ".part"))
    ok("progress only moves forward",
       all(a[0] <= b[0] for a, b in zip(seen, seen[1:])))
    ok("progress ends at the full size", seen and seen[-1] == (len(encoder_body),) * 2)

    Handler.requests = []
    download_file(remote("tiny.encoder.onnx", encoder_body), dest)
    ok("a file already there is not fetched again", not Handler.requests)

    # stopped part-way, then resumed
    os.remove(dest)
    Handler.delay = 0.01
    stop = threading.Event()

    def stop_after_a_megabyte(done, _total):
        if done >= 1024 * 1024:
            stop.set()
    try:
        download_file(remote("tiny.encoder.onnx", encoder_body), dest,
                      stop_after_a_megabyte, stop.is_set)
        ok("a download can be stopped", False)
    except Cancelled:
        ok("a download can be stopped", True)
    Handler.delay = 0.0
    partial = os.path.getsize(dest + ".part") if os.path.exists(dest + ".part") else 0
    ok("a stopped download is not taken for the model", not os.path.exists(dest))
    ok("and what arrived is kept", 0 < partial < len(encoder_body))
    Handler.requests = []
    download_file(remote("tiny.encoder.onnx", encoder_body), dest)
    ok("starting again resumes where it stopped",
       Handler.requests and Handler.requests[0][1] == "bytes=%d-" % partial)
    ok("and the resumed file is whole", open(dest, "rb").read() == encoder_body)

    # a server that ignores the resume
    os.remove(dest)
    with open(dest + ".part", "wb") as handle:
        handle.write(encoder_body[:5000])
    Handler.honour_range = False
    download_file(remote("tiny.encoder.onnx", encoder_body), dest)
    Handler.honour_range = True
    ok("a server that will not resume sends the file again, whole",
       open(dest, "rb").read() == encoder_body)

    # damaged in transit
    os.remove(dest)
    damaged = RemoteFile(base + "/m/tiny.encoder.onnx", len(encoder_body), "0" * 64)
    try:
        download_file(damaged, dest)
        ok("a file with the wrong checksum is refused", False)
    except DownloadError as exc:
        ok("a file with the wrong checksum is refused", "damaged" in str(exc))
    ok("and deleted rather than kept",
       not os.path.exists(dest) and not os.path.exists(dest + ".part"))

    # cut short
    Handler.truncate = 1000
    try:
        download_file(remote("tiny.encoder.onnx", encoder_body), dest)
        ok("a file cut short is refused", False)
    except DownloadError as exc:
        ok("a file cut short is refused", "incomplete" in str(exc))
    Handler.truncate = 0
    ok("and not taken for the model", not os.path.exists(dest))
    download_file(remote("tiny.encoder.onnx", encoder_body), dest)
    ok("and trying again finishes it", open(dest, "rb").read() == encoder_body)

    # the wrong address, and no connection at all
    try:
        download_file(RemoteFile(base + "/m/missing.onnx", 10), os.path.join(folder, "x.onnx"))
        ok("a missing file on the server says so", False)
    except DownloadError as exc:
        ok("a missing file on the server says so", "404" in str(exc))
    try:
        download_file(RemoteFile("http://127.0.0.1:1/none.onnx", 10),
                      os.path.join(folder, "y.onnx"))
        ok("no connection says so in a sentence", False)
    except DownloadError as exc:
        ok("no connection says so in a sentence", "online" in str(exc))

    # a whole model, encoder and decoder
    shutil.rmtree(folder)
    model = CatalogModel("tiny", "Tiny SAM", "for tests",
                         remote("tiny.encoder.onnx", encoder_body),
                         remote("tiny.decoder.onnx", decoder_body, sha=False))
    ok("a model not downloaded is not installed", not model.installed(folder))
    seen = []
    pair = download_model(model, folder, lambda done, total: seen.append((done, total)))
    ok("both files of a model download", pair.complete and model.installed(folder))
    ok("the model's progress covers both files",
       seen[-1] == (model.size, model.size)
       and all(a[0] <= b[0] for a, b in zip(seen, seen[1:])))
    ok("the pair carries the model's name", pair.name == "Tiny SAM")
    ok("and the model folder finds it",
       any(p.encoder == pair.encoder for p in sam.discover_models([folder])))

    server.shutdown()
    print("=" * 60)
    if FAILS:
        print("DOWNLOAD TESTS FAILED: %s" % ", ".join(FAILS))
        return 1
    print("DOWNLOAD TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(SANDBOX, ignore_errors=True)
    sys.exit(code)
