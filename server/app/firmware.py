"""Firmware files for the remote update (OTA) of the loggers.

    <DATA_DIR>/firmware/
      logger-0.3.1.bin, logger-uart-0.3.1.bin    images, one per version and build variant
      manifest.json                              what is offered: {"default": {...}, "<device>": {...}}

A logger asks GET /api/v1/ota?fw=<its version>; the entry for its device name wins over "default".
Every image is checked before it is offered (check_image): an ESP32-S3 app image that carries the
logger's marker "ARKAN-LOGGER-FW;ver=x.y.z;env=usb;" (firmware/include/config.h, FW_TAG). A sketch
from the lab, a file for another chip or a truncated download is refused.

The images can come from a file uploaded on the live page, from a GitHub release made by CI
(tag fw-v<version>, see .github/workflows/ci.yml), or from tools/manage.py publish-fw.
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

from store import atomic_write, iso_now

MARKER = b"ARKAN-LOGGER-FW;"
VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,20}$")
ENV_RE = re.compile(r"^[a-z0-9]{1,8}$")
ESP_IMAGE_MAGIC = 0xE9
ESP32S3_CHIP_ID = 9
MAX_IMAGE = 0x1E0000            # one app slot of min_spiffs.csv (firmware/platformio.ini)
MIN_IMAGE = 64 * 1024


class FirmwareError(ValueError):
    pass


def version_key(v):
    """0.3.10 > 0.3.9; anything that is not digits sorts as 0."""
    out = []
    for part in str(v or "").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def check_image(data):
    """Returns {"version", "env"} read from the image, or raises FirmwareError."""
    if len(data) < MIN_IMAGE:
        raise FirmwareError(f"file too small ({len(data)} bytes): not a logger firmware")
    if len(data) > MAX_IMAGE:
        raise FirmwareError(f"file too large ({len(data)} bytes, the flash slot holds {MAX_IMAGE})")
    if data[0] != ESP_IMAGE_MAGIC:
        raise FirmwareError("not an ESP32 app image (use firmware.bin, not bootloader.bin, partitions.bin or a zip)")
    chip = int.from_bytes(data[12:14], "little")
    if chip != ESP32S3_CHIP_ID:
        raise FirmwareError(f"image built for another chip (chip id {chip}, the logger is an ESP32-S3)")
    i = data.find(MARKER)
    if i < 0:
        raise FirmwareError("no logger marker in the file: not the logger firmware, or a build made before the marker was added (November 2026)")
    end = data.find(b"\0", i, i + 120)
    tag = data[i:end if end > 0 else i + 120].decode("ascii", "replace")
    fields = dict(kv.split("=", 1) for kv in tag.split(";")[1:] if "=" in kv)
    ver, env = fields.get("ver", ""), fields.get("env", "")
    if not VERSION_RE.match(ver) or not ENV_RE.match(env):
        raise FirmwareError(f"unreadable marker {tag!r}")
    return {"version": ver, "env": env}


def file_name(version, env):
    return f"logger-{version}.bin" if env == "usb" else f"logger-{env}-{version}.bin"


class Firmware:
    def __init__(self, store):
        self.store = store
        self.dir = os.path.join(store.root, "firmware")

    # ------------------------------------------------------------------ manifest
    def manifest_path(self):
        return os.path.join(self.dir, "manifest.json")

    def manifest(self):
        try:
            with open(self.manifest_path(), encoding="utf-8") as f:
                man = json.load(f)
            return man if isinstance(man, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def save_manifest(self, man):
        atomic_write(self.manifest_path(), json.dumps(man, indent=2, sort_keys=True) + "\n")

    def entry_for(self, device):
        """(entry, scope) offered to this device: its own entry, else "default"."""
        man = self.manifest()
        if man.get(device):
            return man[device], "device"
        if man.get("default"):
            return man["default"], "default"
        return None, None

    def failed_versions(self, device):
        info = self.store.load_devices().get("devices", {}).get(device) or {}
        return list(info.get("ota_failed", []))

    def offer_for(self, device, fw):
        """The entry a logger running fw should install now, or None.
        Never a downgrade unless the entry is marked force, never a version that was rolled back."""
        entry, _ = self.entry_for(device)
        if not entry or not fw or entry.get("version") == fw:
            return None
        if entry["version"] in self.failed_versions(device):
            return None
        if not entry.get("force") and version_key(entry["version"]) <= version_key(fw):
            return None
        if entry.get("env"):   # a "default" entry must not put the USB build on a UART logger
            dev = self.store.load_devices().get("devices", {}).get(device) or {}
            env = self.reported_env(dev.get("site", ""), device) if dev else None
            if env and env != entry["env"]:
                return None
        return entry

    # ------------------------------------------------------------------ files
    def files(self):
        """Stored images, newest version first: [{"file", "version", "env", "size"}]."""
        out = []
        if os.path.isdir(self.dir):
            for fn in os.listdir(self.dir):
                m = re.match(r"^logger-(?:([a-z0-9]{1,8})-)?([0-9A-Za-z._-]{1,20})\.bin$", fn)
                if m:
                    out.append({"file": fn, "version": m.group(2), "env": m.group(1) or "usb",
                                "size": os.path.getsize(os.path.join(self.dir, fn))})
        return sorted(out, key=lambda x: (version_key(x["version"]), x["env"]), reverse=True)

    def store_image(self, data):
        """Checks and saves an image. Returns (info, file name). A version number is never reused for
        other bytes: loggers already offered that file check its MD5."""
        info = check_image(data)
        os.makedirs(self.dir, exist_ok=True)
        name = file_name(info["version"], info["env"])
        path = os.path.join(self.dir, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                same = f.read() == data
            if not same:
                raise FirmwareError(f"{name} exists already with other content: give the new build a new "
                                    "version number (FW_VERSION in firmware/include/config.h)")
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return info, name

    def offer(self, target, name, force=False, by=None, source=None):
        """Offers a stored image to one device, or to every logger with target "default"."""
        path = os.path.join(self.dir, name)
        if not re.match(r"^[A-Za-z0-9._-]+\.bin$", name) or not os.path.isfile(path):
            raise FirmwareError(f"no stored firmware {name}")
        with open(path, "rb") as f:
            data = f.read()
        info = check_image(data)
        if target != "default":
            dev = self.store.load_devices().get("devices", {}).get(target)
            if dev is None:
                raise FirmwareError(f"no logger {target}")
            env = self.reported_env(dev["site"], target)
            if env and env != info["env"] and not force:
                raise FirmwareError(f"{target} runs the '{env}' build and this file is the '{info['env']}' build: "
                                    "take the matching file (or tick 'force' if the logger was rewired)")
            running = dev.get("fw")
            if running and not force and version_key(info["version"]) <= version_key(running):
                raise FirmwareError(f"{target} runs {running}: {info['version']} is not newer "
                                    "(tick 'allow an older version' to step back on purpose)")
        entry = {"version": info["version"], "env": info["env"], "file": name,
                 "md5": hashlib.md5(data).hexdigest(), "size": len(data), "published": iso_now(),
                 "force": bool(force)}
        if by:
            entry["by"] = by
        if source:
            entry["source"] = source
        with self.store.lock:
            man = self.manifest()
            man[target] = entry
            self.save_manifest(man)
            if target != "default":
                self._clear_failed(target, info["version"])
        if target != "default":
            dev = self.store.load_devices()["devices"][target]
            self.store.event(dev["site"], target, "ota_offered",
                             {"version": info["version"], "by": by or "", "source": source or ""})
        return entry

    def cancel(self, device, by=None):
        with self.store.lock:
            man = self.manifest()
            gone = man.pop(device, None)
            self.save_manifest(man)
        if gone:
            dev = self.store.load_devices()["devices"].get(device)
            if dev:
                self.store.event(dev["site"], device, "ota_cancelled", {"version": gone.get("version"), "by": by or ""})
        return gone

    # ------------------------------------------------------------------ rollback
    def note_rollback(self, site, device):
        """The logger went back to its previous firmware: never offer it that version again
        (until someone offers it again on purpose)."""
        entry, _ = self.entry_for(device)
        if not entry:
            return
        with self.store.lock:
            data = self.store.load_devices()
            info = data.get("devices", {}).get(device)
            if info is None or entry["version"] in info.get("ota_failed", []):
                return
            info.setdefault("ota_failed", []).append(entry["version"])
            self.store.save_devices(data)
        self.store.event(site, device, "ota_failed", {"version": entry["version"]})

    def _clear_failed(self, device, version):
        data = self.store.load_devices()
        info = data.get("devices", {}).get(device)
        if info and version in info.get("ota_failed", []):
            info["ota_failed"].remove(version)
            self.store.save_devices(data)

    # ------------------------------------------------------------------ per logger view
    def reported(self, site, device):
        p = os.path.join(self.store.device_dir(site, device), "settings-reported.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    def reported_env(self, site, device):
        return self.reported(site, device).get("env")

    def recent_events(self, site, device, n=12):
        p = os.path.join(self.store.device_dir(site, device), "events.jsonl")
        out = []
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 65536))
                lines = f.read().decode("utf-8", "replace").splitlines()
        except FileNotFoundError:
            return out
        for ln in reversed(lines):
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("kind") in ("firmware", "ota_offered", "ota_cancelled", "ota_failed") or (
                    e.get("kind") == "boot" and "ota" in str(e.get("reason", ""))):
                out.append(e)
                if len(out) >= n:
                    break
        return out

    def view(self, device):
        dev = self.store.load_devices().get("devices", {}).get(device)
        if dev is None:
            return None
        site = dev["site"]
        entry, scope = self.entry_for(device)
        running = dev.get("fw")
        failed = self.failed_versions(device)
        state = None
        if entry:
            if entry["version"] == running:
                state = "installed"
            elif entry["version"] in failed:
                state = "rolled_back"
            elif self.offer_for(device, running or "0"):
                state = "waiting"
            else:
                state = "not_newer"
        rep = self.reported(site, device)
        return {"device": device, "site": site, "running": running, "env": rep.get("env"),
                "ota_on": (rep.get("settings") or {}).get("ota_on"), "offer": entry, "scope": scope,
                "state": state, "failed": failed, "events": self.recent_events(site, device)}


# ---------------------------------------------------------------------- GitHub releases

class GitHub:
    """Release assets made by CI (tag fw-v<version>). FW_GITHUB_REPO=owner/name, FW_GITHUB_TOKEN optional
    (needed for a private repository: a fine-grained token with Contents read-only on that repository)."""

    API = "https://api.github.com"

    def __init__(self, repo=None, token=None):
        self.repo = repo if repo is not None else os.environ.get("FW_GITHUB_REPO", "")
        self.token = token if token is not None else os.environ.get("FW_GITHUB_TOKEN", "")

    def configured(self):
        return bool(re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", self.repo or ""))

    def _get(self, url, accept, limit):
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "arkan-monitoring",
                                                   "X-GitHub-Api-Version": "2022-11-28"})
        if self.token:
            # Not sent again on the redirect to the download host (that host refuses a second credential).
            req.add_unredirected_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(limit + 1)
        except urllib.error.HTTPError as e:
            hint = " (private repository: set FW_GITHUB_TOKEN)" if e.code == 404 and not self.token else ""
            raise FirmwareError(f"GitHub answered HTTP {e.code}{hint}") from None
        except (urllib.error.URLError, OSError) as e:
            raise FirmwareError(f"GitHub not reachable: {e}") from None
        if len(data) > limit:
            raise FirmwareError("GitHub file too large")
        return data

    def releases(self, n=10):
        if not self.configured():
            raise FirmwareError("FW_GITHUB_REPO is not set on the server")
        data = self._get(f"{self.API}/repos/{self.repo}/releases?per_page={n}", "application/vnd.github+json",
                         2 * 1024 * 1024)
        out = []
        for rel in json.loads(data):
            if rel.get("draft"):
                continue
            assets = [{"id": a["id"], "name": a["name"], "size": a["size"]} for a in rel.get("assets", [])
                      if re.match(r"^logger-.*\.bin$", a.get("name", ""))]
            if assets:
                out.append({"tag": rel.get("tag_name"), "name": rel.get("name") or rel.get("tag_name"),
                            "published": rel.get("published_at"), "prerelease": bool(rel.get("prerelease")),
                            "assets": assets})
        return out

    def download(self, asset_id):
        if not self.configured():
            raise FirmwareError("FW_GITHUB_REPO is not set on the server")
        return self._get(f"{self.API}/repos/{self.repo}/releases/assets/{int(asset_id)}",
                         "application/octet-stream", MAX_IMAGE)

    def asset_label(self, asset_id):
        for rel in self.releases(20):
            for a in rel["assets"]:
                if a["id"] == int(asset_id):
                    return f"GitHub {rel['tag']} {a['name']}"
        return f"GitHub asset {asset_id}"
