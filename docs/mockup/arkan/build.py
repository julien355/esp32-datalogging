#!/usr/bin/env python3
"""Builds docs/mockup/arkan/index.html: the real page (server/app/live.html) with the Arkan UI kit and fixtures.json put inside.

    python3 docs/mockup/arkan/build.py

One file, no network: open index.html in a browser. Every placeholder must be found, or the build stops.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


def main():
    app = os.path.join(HERE, "..", "..", "..", "server", "app")
    page = read(os.path.join(app, "live.html"))
    fx = json.dumps(json.loads(read("fixtures.json")), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    parts = {'<link rel="stylesheet" href="/live/_ui/arkan-ui.css">': "<style>" + read(os.path.join(app, "arkan-ui", "arkan-ui.css")) + "</style>",
             '<script src="/live/_ui/arkan-ui.js"></script>': "<script>" + read(os.path.join(app, "arkan-ui", "arkan-ui.js")) + "</script>",
             "<title>Live</title>": "<title>Arkan Monitoring: design mockup</title>",
             "/*__FIXTURES__*/null": fx}
    for key, text in parts.items():
        if page.count(key) != 1:
            sys.exit(f"live.html: expected 1 x {key}, found {page.count(key)}")
        page = page.replace(key, text)
    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{out}: {os.path.getsize(out) // 1024} kB")


if __name__ == "__main__":
    main()
