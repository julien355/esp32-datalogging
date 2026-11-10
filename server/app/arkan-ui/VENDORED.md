# Arkan UI kit, copy

`arkan-ui.css` and `arkan-ui.js` (kit R1), copied unchanged on 10 November 2026 from `arkan-cmms` (`arkan-ui/`). The logo in
`../live.html` comes from the same place. The kit's master stays where `arkan-cmms/arkan-ui/VENDORED.md` says.

The service serves the two files at `/live/_ui/<file>` (`server.py`, `UI_FILES`); `../live.html` loads them. The monitoring
additions (series colours, small charts, register table) are in the `<style>` of `live.html`, never in these files.
To take a newer kit: copy the two files again, then look at every page in light, dark and high contrast.
