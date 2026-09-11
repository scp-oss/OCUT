#!/usr/bin/env python3
"""
OCUT (OpenCore Update Tool) - local browser UI for updating an EFI/OC
folder's kexts, OpenCore.efi, Drivers, theme, and migrating config.plist
across OpenCore versions. Pure stdlib (http.server), no pip install
needed. Run on the machine that has internet access and the real EFI
folder - not from a sandbox with no GitHub access.

    python3 server.py [--port 8765]

Then open http://127.0.0.1:8765 in a browser and point it at any EFI/OC
folder (a live USB/disk partition, or a local clone of your OpenCore
config repo). Every destructive action (update, migrate) requires that
path to be typed into the UI explicitly - nothing runs against a
hardcoded path, and this repo itself holds no EFI data.
"""
import argparse
import json
import mimetypes
import os
import plistlib
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import core

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        fs_path = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not fs_path.startswith(STATIC_DIR) or not os.path.isfile(fs_path):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        with open(fs_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # keep stdout quiet; errors still print via traceback below

    # ---------------------------------------------------------------- GET

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        try:
            if parsed.path == "/api/browse":
                path = qs.get("path", [""])[0]
                self._json(200, core.browse_dir(path))
            elif parsed.path == "/api/scan":
                root = qs.get("root", [""])[0]
                self._json(200, core.scan_root(root))
            elif parsed.path == "/api/check-updates":
                root = qs.get("root", [""])[0]
                channel = qs.get("channel", ["stable"])[0]
                self._json(200, core.check_updates(root, channel))
            elif parsed.path == "/api/components":
                self._json(200, core.load_components())
            elif parsed.path == "/api/kext-catalog":
                self._json(200, core.get_kext_catalog())
            else:
                self._serve_static(parsed.path)
        except Exception as e:
            traceback.print_exc()
            self._json(400, {"error": str(e)})

    # --------------------------------------------------------------- POST

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._read_json_body()
            log = []

            if parsed.path == "/api/pick-folder":
                self._json(200, core.pick_folder_native(body.get("prompt", "Choose the EFI/OC folder")))

            elif parsed.path == "/api/components/add":
                result = core.add_component(body["repo"], body["kexts"], name=body.get("name"))
                self._json(200, {"components": result})

            elif parsed.path == "/api/components/remove":
                result = core.remove_component(body["name"])
                self._json(200, {"components": result})

            elif parsed.path == "/api/kext/add-from-catalog":
                self._json(200, core.add_kexts_from_catalog(body["names"]))

            elif parsed.path == "/api/kext/list-in-folder":
                self._json(200, {"kexts": core.list_kexts_in_folder(body["folder"])})

            elif parsed.path == "/api/kext/import-from-folder":
                self._json(200, core.import_kext_from_folder(body["root"], body["folder"], body["bundle"]))

            elif parsed.path == "/api/kext/toggle":
                self._json(200, core.set_kext_enabled(body["root"], body["bundle"], body["enabled"]))

            elif parsed.path == "/api/kext/add-to-config":
                self._json(200, core.add_kext_to_config(body["root"], body["bundle"]))

            elif parsed.path == "/api/kext/remove-from-config":
                self._json(200, core.remove_kext_from_config(body["root"], body["bundle"]))

            elif parsed.path == "/api/kext/remove-from-config-bulk":
                self._json(200, core.remove_kexts_from_config_bulk(body["root"], body["bundles"]))

            elif parsed.path == "/api/driver/toggle":
                self._json(200, core.set_driver_enabled(body["root"], body["file"], body["enabled"]))

            elif parsed.path == "/api/driver/add-to-config":
                self._json(200, core.add_driver_to_config(body["root"], body["file"]))

            elif parsed.path == "/api/driver/remove-from-config":
                self._json(200, core.remove_driver_from_config(body["root"], body["file"]))

            elif parsed.path == "/api/driver/remove-from-config-bulk":
                self._json(200, core.remove_drivers_from_config_bulk(body["root"], body["files"]))

            elif parsed.path == "/api/driver/fetch-from-opencore":
                result = core.fetch_driver_from_opencore(body["root"], body["file"], body["channel"], log)
                self._json(200, {"result": result, "log": log})

            elif parsed.path == "/api/update-kext":
                result = core.apply_kext_component(body["component"], body["root"], body["channel"], log)
                self._json(200, {"result": result, "log": log})

            elif parsed.path == "/api/update-opencore":
                result = core.apply_opencore(body["root"], body["channel"], body["parts"], log)
                self._json(200, {"result": result, "log": log})

            elif parsed.path == "/api/apply-theme":
                result = core.apply_theme(body["repo"], body["root"], log, ref=body.get("ref"))
                self._json(200, {"result": result, "log": log})

            elif parsed.path == "/api/migrate-config":
                merged, report = self._migrate(body)
                self._json(200, {"report": report, "preview": _plist_preview(merged)})

            elif parsed.path == "/api/migrate-config/save":
                merged, report = self._migrate(body)
                out_path = os.path.join(body["root"], body.get("out_name", "config.migrated.plist"))
                with open(out_path, "wb") as f:
                    plistlib.dump(merged, f)
                self._json(200, {"saved_to": out_path, "report": report})

            else:
                self._json(404, {"error": "no such endpoint"})
        except Exception as e:
            traceback.print_exc()
            self._json(400, {"error": str(e)})

    def _migrate(self, body):
        """body: {root, new_opencore_zip_channel} - fetches the new
        version's Docs/Sample.plist straight from the OpenCorePkg release
        so the user doesn't have to hunt it down manually."""
        root = body["root"]
        old_config_path = os.path.join(root, "config.plist")
        channel = body.get("channel", "stable")

        tag, assets, _ = core.resolve_release(core.OPENCORE_REPO, channel)
        asset_name, asset_url = core.pick_asset(assets)
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, asset_name)
            core.download(asset_url, zip_path)
            extract_dir = os.path.join(tmp, "extracted")
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(extract_dir)
            sample_path = core.find_in_tree(extract_dir, "Sample.plist")
            if not sample_path:
                raise RuntimeError(f"Docs/Sample.plist not found in {asset_name}")
            merged, report = core.migrate_config(old_config_path, sample_path)
        report["target_version"] = tag
        report["channel"] = channel
        return merged, report


def _plist_preview(d, max_len=20000):
    """A quick top-level summary for the browser, not the full plist (could
    be large / binary-heavy with ROM/UUID data)."""
    def summarize(v, depth=0):
        if depth > 2:
            return "..."
        if isinstance(v, dict):
            return {k: summarize(vv, depth + 1) for k, vv in v.items()}
        if isinstance(v, list):
            return f"[{len(v)} item(s)]"
        if isinstance(v, bytes):
            return f"<{len(v)} bytes>"
        return v
    text = json.dumps(summarize(d), indent=2, default=str)
    return text[:max_len]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open the browser on startup")
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"EFI updater running at {url}  (Ctrl+C to stop)")

    if not args.no_browser:
        # Fire after a short delay in a background thread so a slow/absent
        # browser launch never blocks server startup - opening a tab is a
        # nice-to-have, not something a failure here should affect.
        def _open_browser():
            time.sleep(0.3)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
