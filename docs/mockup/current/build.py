#!/usr/bin/env python3
"""Builds docs/mockup/current/index.html: the site page (server/app/live.html, with its page Current & balance since
v0.10.0) with the saved answers of docs/mockup/arkan/fixtures.json and 14 days of simulated currents of the three phases.
mock-server.js answers the page's /api/v1/quality/<site>/current requests in the page, with the fields and rules of
server/app/quality.py.

    python3 docs/mockup/current/build.py

Every insertion point must be found once in live.html, or the build stops. One file, no network.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..", "..")
APP = os.path.join(ROOT, "server", "app")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main():
    fx = json.loads(read(os.path.join(ROOT, "docs", "mockup", "arkan", "fixtures.json")))
    page = read(os.path.join(APP, "live.html"))
    mock = read(os.path.join(HERE, "mock-server.js"))
    fxs = json.dumps(fx, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page_marker = "// ------------------------------------------------------------------ page\n"
    parts = [
        # the server's side of the current page, inside the page's own script, before the page starts
        (page_marker, mock + "\n" + page_marker),
        ("Design mockup · simulated data, 14 days · nothing is sent to a logger",
         "Design mockup · <b>Current &amp; balance</b> page · simulated data, 14 days"),
        # then the kit and the saved answers, as docs/mockup/arkan/build.py does
        ('<link rel="stylesheet" href="/live/_ui/arkan-ui.css">', "<style>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.css")) + "</style>"),
        ('<script src="/live/_ui/arkan-ui.js"></script>', "<script>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.js")) + "</script>"),
        ("<title>Live</title>", "<title>Arkan Monitoring: current per phase and balance</title>"),
        ("/*__FIXTURES__*/null", fxs),
    ]
    for key, text in parts:
        if page.count(key) != 1:
            sys.exit(f"live.html: expected 1 x {key!r}, found {page.count(key)}")
        page = page.replace(key, text)
    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{out}: {os.path.getsize(out) // 1024} kB")


if __name__ == "__main__":
    main()
