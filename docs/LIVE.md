# Live data every 15 seconds

## The limit in OED

OED is not built for live data:
- Readings enter only through CSV uploads.
- Graphs load when a person opens or redraws them, with no auto refresh.
- The hourly and daily views are refreshed by scheduled jobs.

There is also **no plugin system** to add a live widget without changing OED's code.

## Options

| Option | How | Verdict |
|---|---|---|
| **A. Live page beside OED** | The logger sends a small snapshot every 15 s; the ingest service keeps it in memory and serves a live page at `/live/<site>/` that refreshes every 15 s. Same login as OED. OED stays unchanged for history | **Recommended.** No change to OED, very little RAM, nothing written to disk every 15 s |
| B. Push 15-second readings into OED | Upload every 15 s instead of every 5 min | OED still shows them only on redraw, and stores 4x more rows in PostgreSQL (more RAM and disk). Not live |
| C. Add a "Live" page inside OED | Change OED's React client and server to add a live view | A fork to keep up with OED's updates; MPL-2.0 requires publishing the changed files. Possible later, or proposed to the OED project |

## Option A in detail

**Which values are live** is a list per site in `site.json`, so it can change without code:

```json
"live": {
  "refresh_s": 15,
  "values": ["p", "s", "pf", "f", "v1", "v2", "v3", "i1", "i2", "i3",
             "TH1.temp", "TH1.hum", "TH2.temp", "TH2.hum"]
}
```

Default for Adab:
- total kW and kVA, power factor, frequency;
- voltage and current per phase;
- temperature and humidity of both sensors (`TH1` on the board, `TH2` the AM2301), each with its location label;
- logger status (online, last seen, WiFi signal).

**Logger:**
- Every 15 s, after reading the meter, it POSTs the snapshot to `/api/v1/live` (about 300 bytes, on a kept-open HTTPS connection).
- The snapshot is **not** written to the SD card and not resent if lost: the next one replaces it 15 s later.
- The 1-minute records go on as before, through the SD queue to `/api/v1/ingest`. **History stays complete; only live is best effort.**
- Data use: about 2 MB a day on the hotel WiFi.

**Ingest service:**
- Keeps the last snapshot and the **last 60 minutes** (240 points) per site **in memory only**: a few kB per site.
- Serves `/api/v1/live/<site>` (JSON) and the page `/live/<site>/`.
- A restart empties the 60 minutes; they refill as snapshots arrive.
- The live alarms (A04 phase lost, A07 frequency) are checked on the snapshots, so they react within 15 to 30 s.

**Live page `/live/<site>/`:**
- Big tiles for the chosen values, each with a 60-minute sparkline.
- A status line: "Live, updated 4 s ago", or "No data for 2 min" in red.
- The open alarms.
- Links to the site's OED graphs.
- Plain HTML and a few lines of JavaScript that fetch the JSON every 15 s; no chart library.
- Behind the same login as OED (`hub-users.caddy`).
- Readable on a phone.

**`/live/`** lists all sites with their status and total kW: the multi-site live overview.

## Getting from OED to the live page

OED has no setting for a custom menu link. The live page links to OED, and people bookmark `/live/` as the start page. If a single entry point is wanted later, option C (a small "Live" link added to OED's header) is the smallest change to OED.
