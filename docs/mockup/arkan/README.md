# The site page with saved answers (mockup of the Arkan design)

**In service since release v0.7.0:** the page is `server/app/live.html`, with the Arkan UI kit in `server/app/arkan-ui/`. This folder
keeps the same page as **one file with simulated data** (14 days), for reviews without a server: open **[`index.html`](index.html)**
in a browser. Nothing is sent to a logger.

| | |
|---|---|
| ![Live now](img/desk-now.png) | ![Live now, dark](img/dark-now.png) |
| ![Settings](img/dark-settings.png) | ![Tablet rail](img/rail-now.png) |

## What the Arkan design changed (10 November 2026)

- **Side bar of the CMMS**: logo, site, **View as**, the pages in groups (History, Weather, Logger, Platform), **Settings** at the bottom
  with the live state. Icon rail from 700 px, bottom tabs and a "More" sheet on a phone.
- **View as** shows who is logged in (the Caddy login) and the rights: `Admin · <login>` when the login is in `ADMIN_USERS`,
  `Viewer · <login>` otherwise. An admin can switch to Viewer to see the pages as the other logins do (Firmware update hidden).
  It changes the browser only, never the rights on the server.
- **Settings**: the kit's display settings (mode: system, light, dark, high contrast; density; text size; motion; reset), saved in the
  browser as in the CMMS and shared with it on the same address. Also who is logged in, and the site details from `site.json` (read only).
- **Meter registers** is a page of the same shell (`#register`).
- The link to Open Energy Dashboard is removed from the menu (review of 10 November).
- Charts, tables, values, texts and the 15 s refresh are those of the pages of v0.6.0.
- Every chart shows both axes with their scales and names; in a row of cards the figures and the charts line up (review of 10 November).

## Files

`capture.py` saves the answers of a local service as `fixtures.json` (and makes up what the simulator does not send: register table
report, firmware history, day-ahead forecast, one open alarm). `build.py` takes `server/app/live.html`, puts the kit and
`fixtures.json` inside and writes `index.html`. In `live.html`, the block `if (MOCK)` answers the page's requests from those saved
answers; on the server `FX` is `null` and the block does nothing.

Rebuild after a change of the page: start the service and the simulator as in [`../README.md`](../README.md) with `ADMIN_USERS=julien`, then

```bash
python3 docs/mockup/arkan/capture.py
python3 docs/mockup/arkan/build.py
```
