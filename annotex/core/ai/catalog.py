"""SAM models Annotex knows how to fetch - one click, the way LabelMe does it.

The files are the quantized Segment Anything exports LabelMe itself
downloads, published on LabelMe's GitHub releases.  They are the reference
`segment-anything` ONNX export, so `SamRuntime` drives them unchanged.

Nothing here runs unless the person asks for a model.  A download:

* goes to a `.part` file first and is renamed only once it is whole, so a
  half-finished file is never mistaken for a model;
* picks up where it stopped if it is started again;
* is checked against the exact size published with the release, and against
  a SHA-256 where one is known, before it is kept;
* can be cancelled from another thread at any moment.

Standard library only (urllib), and no Qt: the dialog runs this on a worker.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.error
import urllib.request

from .sam import ModelPair, models_dir

CHUNK = 1024 * 1024
TIMEOUT = 30                     # seconds without a byte before giving up
USER_AGENT = "Annotex model download"

LABELME_SAM = "https://github.com/wkentaro/labelme/releases/download/sam-20230416/"
# EfficientSAM, exported by LabelMe's author; the checksums are the ones his
# own osam publishes, and they match the files as downloaded.
EFFICIENT_SAM = "https://github.com/labelmeai/efficient-sam/releases/download/onnx-models-20231225/"


class DownloadError(RuntimeError):
    """The download could not finish.  The message is written for a person."""


class Cancelled(DownloadError):
    """The person stopped the download."""


class RemoteFile:
    def __init__(self, url, size, sha256=""):
        self.url = url
        self.size = int(size)
        self.sha256 = sha256.lower()

    @property
    def filename(self) -> str:
        return self.url.rsplit("/", 1)[-1]


class CatalogModel:
    """A model that can be downloaded: an encoder and a decoder."""

    def __init__(self, key, name, blurb, encoder, decoder):
        self.key = key
        self.name = name
        self.blurb = blurb
        self.encoder = encoder
        self.decoder = decoder

    @property
    def files(self):
        return (self.encoder, self.decoder)

    @property
    def size(self) -> int:
        return self.encoder.size + self.decoder.size

    def describe(self) -> str:
        return "%s  ·  %.0f MB  ·  %s" % (self.name, self.size / (1024.0 * 1024.0),
                                          self.blurb)

    def paths(self, folder=None):
        folder = str(folder or models_dir())
        return (os.path.join(folder, self.encoder.filename),
                os.path.join(folder, self.decoder.filename))

    def installed(self, folder=None) -> bool:
        """Both files are there and whole."""
        for remote, path in zip(self.files, self.paths(folder)):
            try:
                if os.path.getsize(path) != remote.size:
                    return False
            except OSError:
                return False
        return True

    def pair(self, folder=None) -> ModelPair:
        encoder, decoder = self.paths(folder)
        return ModelPair(self.name, encoder, decoder)


CATALOG = [
    CatalogModel(
        "sam_vit_b", "SAM ViT-B", "recommended - every kind of click, a few seconds an image",
        RemoteFile(LABELME_SAM + "sam_vit_b_01ec64.quantized.encoder.onnx", 99827688,
                   "3346b9cc551c9902fbf3b203935e933592b22e042365f58321c17fc12641fd6a"),
        RemoteFile(LABELME_SAM + "sam_vit_b_01ec64.quantized.decoder.onnx", 8743656,
                   "edbcf1a0afaa55621fb0abe6b3db1516818b609ea9368f309746a3afc68f7613")),
    CatalogModel(
        "efficient_sam_vitt", "EfficientSAM ViT-T",
        "fastest - about a second an image, but no exclude clicks",
        RemoteFile(EFFICIENT_SAM + "efficient_sam_vitt_encoder.onnx", 24799761,
                   "7a73ee65aa2c37237c89b4b18e73082f757ffb173899609c5d97a2bbd4ebb02d"),
        RemoteFile(EFFICIENT_SAM + "efficient_sam_vitt_decoder.onnx", 16565728,
                   "e1afe46232c3bfa3470a6a81c7d3181836a94ea89528aff4e0f2d2c611989efd")),
    CatalogModel(
        "sam_vit_l", "SAM ViT-L", "more accurate, slower",
        RemoteFile(LABELME_SAM + "sam_vit_l_0b3195.quantized.encoder.onnx", 322569107),
        RemoteFile(LABELME_SAM + "sam_vit_l_0b3195.quantized.decoder.onnx", 8743680)),
    CatalogModel(
        "sam_vit_h", "SAM ViT-H", "most accurate, slowest",
        RemoteFile(LABELME_SAM + "sam_vit_h_4b8939.quantized.encoder.onnx", 656243518),
        RemoteFile(LABELME_SAM + "sam_vit_h_4b8939.quantized.decoder.onnx", 8743672)),
]


def by_key(key):
    for model in CATALOG:
        if model.key == key:
            return model
    return None


def name_for(path) -> str:
    """The catalogue's name for a downloaded file, or ""."""
    base = os.path.basename(str(path or ""))
    for model in CATALOG:
        if base in (model.encoder.filename, model.decoder.filename):
            return model.name
    return ""


# ══════════════════════════════════════════════════════════════
# DOWNLOADING
# ══════════════════════════════════════════════════════════════
def _sha256(path, cancelled):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancelled():
                raise Cancelled("the download was cancelled")
            block = handle.read(CHUNK)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def download_file(remote, dest, progress=None, cancelled=None) -> str:
    """Fetch one file to `dest`, resuming a `.part` left from before.

    `progress(done_bytes, total_bytes)` is called as it goes; `cancelled()`
    returning True stops it (the `.part` is kept, so it can resume)."""
    progress = progress or (lambda done, total: None)
    cancelled = cancelled or (lambda: False)
    if os.path.isfile(dest) and os.path.getsize(dest) == remote.size:
        progress(remote.size, remote.size)
        return dest
    folder = os.path.dirname(dest) or "."
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise DownloadError("the model folder cannot be created:\n%s\n\n%s" % (folder, exc))

    part = dest + ".part"
    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > remote.size:
        os.remove(part)
        have = 0
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        free = None
    if free is not None and free < remote.size - have:
        raise DownloadError("there is not enough free space in %s - %s needs %.0f MB more"
                            % (folder, remote.filename,
                               (remote.size - have) / (1024.0 * 1024.0)))

    if have < remote.size:
        request = urllib.request.Request(remote.url, headers={"User-Agent": USER_AGENT})
        if have:
            request.add_header("Range", "bytes=%d-" % have)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if have and getattr(response, "status", 200) != 206:
                    have = 0                 # the server ignored the resume; start over
                with open(part, "ab" if have else "wb") as out:
                    progress(have, remote.size)
                    while True:
                        if cancelled():
                            raise Cancelled("the download was cancelled")
                        block = response.read(CHUNK)
                        if not block:
                            break
                        out.write(block)
                        have += len(block)
                        progress(have, remote.size)
        except DownloadError:
            raise
        except urllib.error.HTTPError as exc:
            raise DownloadError("the server refused %s (HTTP %s)" % (remote.filename, exc.code))
        except urllib.error.URLError as exc:
            raise DownloadError("the model could not be downloaded - is this machine "
                                "online?\n\n%s" % getattr(exc, "reason", exc))
        except OSError as exc:
            raise DownloadError("the download of %s stopped: %s" % (remote.filename, exc))

    size = os.path.getsize(part)
    if size != remote.size:
        raise DownloadError("%s arrived incomplete (%d of %d bytes) - try again to "
                            "resume it" % (remote.filename, size, remote.size))
    if remote.sha256 and _sha256(part, cancelled) != remote.sha256:
        os.remove(part)
        raise DownloadError("%s arrived damaged (its checksum does not match) and was "
                            "deleted - try again" % remote.filename)
    os.replace(part, dest)
    return dest


def download_model(model, folder=None, progress=None, cancelled=None) -> ModelPair:
    """Fetch both files of a catalogue model; `progress` sees the pair's total."""
    progress = progress or (lambda done, total: None)
    folder = str(folder or models_dir())
    total = model.size
    before = 0
    for remote, path in zip(model.files, model.paths(folder)):
        offset = before
        download_file(remote, path,
                      lambda done, _total, offset=offset: progress(offset + done, total),
                      cancelled)
        before += remote.size
    return model.pair(folder)
