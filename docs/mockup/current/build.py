#!/usr/bin/env python3
"""Builds docs/mockup/current/index.html: the site page of the Arkan mockup (server/app/live.html with
docs/mockup/arkan/fixtures.json) plus the PROPOSED page "Current & balance" (#current, menu group Power quality).

    python3 docs/mockup/current/build.py

Nothing in server/ is changed: the new page (current.js, current.css) and the mockup's server answers (mock-server.js, with
simulated 1-minute currents of the three phases) are put into a copy of the page here, at fixed places of live.html. Every
place must be found once, or the build stops. One file, no network.
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
    js, css, mock = (read(os.path.join(HERE, n)) for n in ("current.js", "current.css", "mock-server.js"))
    fxs = json.dumps(fx, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    page_marker = "// ------------------------------------------------------------------ page\n"
    i_card = "          else if (prof.rated_a) extra = capBar(mx / prof.rated_a, `of the ${prof.rated_a} A main breaker (highest phase)`);\n"
    iu_tile = "`highest hourly mean · ${esc(L.iu.id)} at ${L.iu.v} %, not below ${j.i_floor_a} A of mean current`"
    parts = [
        # the proposed page and the mockup's answers, inside the page's own script, before the page starts
        (page_marker, js + "\n" + mock + "\n" + page_marker),
        # Live now: the current card gets the unbalance and the estimated neutral of the last snapshot, and a link to the page
        (i_card, i_card + "          extra += curLive(V, M);\n"),
        # Power quality: the current imbalance tile links to the page
        (iu_tile, iu_tile[:-1] + ' · <a href="#current">details</a>`'),
        ("const LABEL = {quality: 'power quality', voltage: 'power quality', pf: 'power quality',",
         "const LABEL = {quality: 'power quality', voltage: 'power quality', pf: 'power quality', current: 'current per phase',"),
        ("</style>\n<script src=\"/live/_ui/arkan-ui.js\"></script>", css + "</style>\n<script src=\"/live/_ui/arkan-ui.js\"></script>"),
        ("Design mockup · simulated data, 14 days · nothing is sent to a logger",
         "Design mockup · <b>Current &amp; balance</b> page proposed for review · simulated data, 14 days"),
        # then the kit and the saved answers, as docs/mockup/arkan/build.py does
        ('<link rel="stylesheet" href="/live/_ui/arkan-ui.css">', "<style>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.css")) + "</style>"),
        ('<script src="/live/_ui/arkan-ui.js"></script>', "<script>" + read(os.path.join(APP, "arkan-ui", "arkan-ui.js")) + "</script>"),
        ("<title>Live</title>", "<title>Arkan Monitoring: current per phase and balance (proposal)</title>"),
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
