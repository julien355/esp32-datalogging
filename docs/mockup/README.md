# Dashboard mockup

> **Since release v0.7.0 (10 November 2026)** the pages are in the Arkan design of the CMMS, with View as and Settings: [`arkan/`](arkan/README.md) holds the page as it is now, with saved answers. The screens below are the earlier design.

How `arkan-monitoring.duckdns.org` should look for the Adab hotel, with **simulated data** (14 days).
Open **[`index.html`](index.html)** in a browser (it needs the `img/` folder beside it).

| Screen | Address | What it is |
|---|---|---|
| Start page: all sites | `/live/` | Screenshot of the real page (`server/app/live.html`) |
| Adab: live now (desktop and phone) | `/live/adab/` | Screenshot of the real page, fed every 15 s by the simulated logger |
| Site page history (built) | `/live/adab/#power`, `#day`, `#energy`, `#week`, `#temperature` | Screenshots of the history pages of the side menu (approved design, built 8 November 2026) |
| Site page power quality (built) | `/live/adab/#quality`, `#voltage`, `#pf` | Screenshots of the power quality pages of the side menu (built 9 November 2026), over 31 days |
| Power over two weeks | `/` (OED) | Line, group `adab`, unit kWh, rate Hour |
| One day, minute by minute | `/` (OED) | Line zoomed on one day after Redraw |
| Energy per day | `/` (OED) | Bar, interval Day |
| This week against last week | `/` (OED) | Compare, Week |
| Temperature, humidity | `/` (OED) | Line, meters `adab-TH1-*` and `adab-TH2-*` |
| What OED will not show | `/` (OED) | Bar on a temperature meter: OED refuses raw units |

**What is real and what is drawn.**
- The two live screens are screenshots of our ingest service running locally: what you see is what it serves today.
- The OED screens are **redrawn** from the same data to show what each graph will contain, with the settings of
  [tutorial 3](../tutorials/3-OPEN-ENERGY-DASHBOARD.md) Part D. OED itself (v1.0.0) was not running for the mockup:
  its menus, colours and fonts will differ in detail.
- The simulator repeats the same day pattern, so every full day has about the same kWh and the week comparison is flat.

## Rebuild it

From the repository root (Python 3.9+, Node with Playwright for the screenshots):

```bash
D=$(mktemp -d)
python3 server/tools/manage.py --data $D init
python3 server/tools/manage.py --data $D add-site adab --name "Adab hotel" --contracted-kva 82.5 --rated-a 200 --lat -8.4766 --lon 115.4319
python3 server/tools/manage.py --data $D add-device adab LOG-0001          # prints the token
DATA_DIR=$D BIND=127.0.0.1 PORT=8800 python3 server/app/server.py &
python3 server/tools/simulate_logger.py --token <token> --backlog-hours 336 --event dip --live &
# wait about 10 minutes for the live sparklines, then:
node docs/mockup/screenshots.js http://127.0.0.1:8800 docs/mockup/img
python3 server/tools/manage.py --data $D daily adab
python3 docs/mockup/build_mockup.py --data $D
```

Files: `template.html` (page and charts, no library), `build_mockup.py` (puts the data in), `screenshots.js`
(the live page screenshots), `index.html` (the result), `img/`.
