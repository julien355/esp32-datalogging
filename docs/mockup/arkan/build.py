#!/usr/bin/env python3
"""Builds docs/mockup/arkan/index.html: page.html with the Arkan UI kit, the logo and fixtures.json put inside.

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
    page = read("page.html")
    fx = json.dumps(json.loads(read("fixtures.json")), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    brand = read("brand-text.html").strip().replace("O&amp;M · CMMS", "Monitoring")
    if "Monitoring" not in brand:
        sys.exit("brand-text.html: the product label was not found")
    parts = {"/*__KIT_CSS__*/": (read("arkan-ui.css"), 1), "/*__KIT_JS__*/": (read("arkan-ui.js"), 1),
             "<!--__MARK__-->": (read("brand-mark.html").strip(), 2), "<!--__BRANDTXT__-->": (brand, 1),
             "/*__FIXTURES__*/null": (fx, 1)}
    for key, (text, n) in parts.items():
        if page.count(key) != n:
            sys.exit(f"page.html: expected {n} x {key}, found {page.count(key)}")
        if key == "<!--__MARK__-->":   # drawn twice (side bar, top bar): the gradient ids of the second copy get their own names
            if "m1-" not in text:
                sys.exit("brand-mark.html: gradient ids m1-* not found")
            page = page.replace(key, text, 1).replace(key, text.replace("m1-", "m2-"), 1)
        page = page.replace(key, text)
    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"{out}: {os.path.getsize(out) // 1024} kB")


if __name__ == "__main__":
    main()
