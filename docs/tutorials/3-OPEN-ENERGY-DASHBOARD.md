# Tutorial 3: Open Energy Dashboard (OED) for Arkan monitoring

Draft, 7 November 2026. For the operator who installs and runs the dashboard, and for the owner who approves the steps that need `sudo`.
Level: beginner. Every term is explained the first time it appears, and again in the [glossary](#appendix-b-glossary).

| | |
|---|---|
| **For** | The operator (user `ai`), with the **owner** for the `sudo` steps, the Caddy reload and every approval |
| **Where** | Your laptop (Docker Desktop, PowerShell), `hermes-vps` over SSH, and a web browser |
| **Time** | About half a day for Parts A and B; 10 minutes a day for Part C until the automatic push exists |
| **Before** | [Tutorial 2](2-VPS-SETUP.md): the ingest service runs, the site `adab` and the logger `LOG-0001` exist |
| **After** | Nothing. The live page `/live/` works with or without OED |

**Status.**
- The deploy files in [`server/deploy/oed/`](../../server/deploy/oed/) are **DRAFT, NOT TESTED**. Run Part A once on a test machine, or very carefully on the VPS, and correct this tutorial with what you see.
- The **automatic push** from our ingest service to OED (every 5 minutes) is **not built yet**. Until it is, data goes into OED with our exporter and OED's CSV upload (Part C).

**Conventions.**
- Each command is in its own box, one command per box. The line above the box says **where it runs**: **Laptop (PowerShell)**, **VPS, user ai** (after `ssh hermes-vps`, without `sudo`), **VPS, owner with sudo** (run by the owner only), or **Browser**. Do not type the prompt (`ai@hermes-vps:~$`, `PS C:\...>`).
- `<...>` is a placeholder: replace it, brackets included, with your value. Never paste a real password into this file or into a commit.
- **to verify** marks a point that could not be checked in OED's code or documentation. Check it the first time and update this tutorial.

**Sources.** Every OED fact here comes from the OED repository at tag **`v1.0.0`** (files read through `raw.githubusercontent.com`) or from the OED help pages for version 1.0.0 (read from the source of the OED website, repository `OpenEnergyDashboard/OpenEnergyDashboard.github.io`, folder `helpV1_0_0/`). The source is named next to each fact. The website `openenergydashboard.org` itself and `github.com` were not reachable from the session that wrote this tutorial.

## Contents

- [Part 0: what OED is, and where everything lives](#part-0-what-oed-is-and-where-everything-lives)
- [Part A: install OED on hermes-vps](#part-a-install-oed-on-hermes-vps)
- [Part B: set up Adab in OED](#part-b-set-up-adab-in-oed)
- [Part C: load data into OED](#part-c-load-data-into-oed)
- [Part D: use OED](#part-d-use-oed)
- [Part E: maintenance](#part-e-maintenance)
- [Part F: troubleshooting](#part-f-troubleshooting)
- [Appendix A: command cheat sheet](#appendix-a-command-cheat-sheet)
- [Appendix B: glossary](#appendix-b-glossary)
- [Appendix C: version record and open points](#appendix-c-version-record-and-open-points)

---

## Part 0: what OED is, and where everything lives

### 0.1 What OED is

**Open Energy Dashboard (OED)** is a free, open-source web application for energy dashboards (licence MPL-2.0). It was built for campuses with many buildings and meters. It has two parts:
- **web**: a Node.js program (a JavaScript server) that serves the pages and the graphs;
- **database**: PostgreSQL, where OED stores meters, readings, units, groups and users.

The owner decided on 30 October 2026 that OED is the platform's dashboard, **deployed as it is** (we do not change its code), with our settings ([`REUSE.md`](../REUSE.md) section 7, [`PLAN.md`](../PLAN.md) section 4.2).

What OED gives us:
- **graphs** of meters and of groups of meters: line, bar, compare and map (the graph types of v1.0.0: `src/client/app/types/redux/graph.ts`);
- **units and conversions** (kWh, Celsius, and units we add);
- **groups** (the site, then all sites);
- **export** of graph data as CSV;
- its own **admin pages** to manage all of this.

### 0.2 What OED is not

- **Not live.** OED shows readings only after they are uploaded, and its hourly and daily summaries only after a "view refresh" (section E.1). A graph does not refresh by itself ([`LIVE.md`](../LIVE.md)). **The live page stays ours**, at `/live/`.
- **Not our record.** The record is our per-site CSV files in `/srv/arkan-monitoring/data/`. OED holds a copy that can be rebuilt from them (section E.5).
- **No alarms.** Alarms and WhatsApp messages stay in our ingest service.
- **No logger API.** The logger never talks to OED. It posts to our ingest service.
- **No Indonesian.** OED v1.0.0 has English, French and Spanish only (`src/client/app/translations/data.js`).

### 0.3 How it fits together

```text
 Adab hotel                          hermes-vps (Ubuntu, Docker, native Caddy)
 +-------------+   HTTPS (internet)  +--------------------------------------------------------------+
 | ESP32 logger| ------------------> | Caddy  arkan-monitoring.duckdns.org                          |
 | LOG-0001    |  /api/v1/ingest     |   /api/v1/ingest, /ota, /config...  (no web login, token)    |
 +-------------+  /api/v1/live       |   /live/, /api/v1/*, /health   (Arkan login) -> 127.0.0.1:8800
                                     |   everything else, /           (Arkan login) -> 127.0.0.1:8810
                                     |                                                              |
 People (browser)  ----------------> |  +---------------------------+     +-----------------------+ |
                                     |  | ingest service (ours)     |     | OED web (Node.js)     | |
                                     |  | arkan-monitoring-ingest   |     | arkan-oed-web         | |
                                     |  | 127.0.0.1:8800            |     | 127.0.0.1:8810        | |
                                     |  | writes the day files      |     |        |              | |
                                     |  +-------------+-------------+     | OED database          | |
                                     |                |                   | arkan-oed-db (Postgres)| |
                                     |                v                   +-----------^-----------+ |
                                     |  /srv/arkan-monitoring/data/                    |             |
                                     |    sites/adab/LOG-0001/raw/...csv (UTC)         |             |
                                     |    export/oed/adab/*.csv (WITA)  ---------------+             |
                                     |       today: manage.py export-oed + curl (Part C)            |
                                     |       later: automatic push every 5 min (not built yet)      |
                                     +--------------------------------------------------------------+
```

### 0.4 Where everything lives

| What | Where | Notes |
|---|---|---|
| Deploy files for OED (draft) | [`server/deploy/oed/`](../../server/deploy/oed/) in this repository | `Dockerfile`, `docker-compose.yml`, `oed.env.example`, `postgresql-oed.conf`, `initdb/10-oed-user.sh`, `monitoring-oed.caddy`, `oed-backup.sh` |
| Same files on the VPS | `/opt/arkan-monitoring/server/deploy/oed/` | the repository is checked out at a tag ([`VPS-SETUP.md`](../VPS-SETUP.md) section 4) |
| OED secrets | `/srv/arkan-monitoring/oed/oed.env` | **outside** the repository, mode 600, owner `ai` |
| OED database files | `/srv/arkan-monitoring/oed-postgres/pgdata/` | owned by the `postgres` user of the container |
| Our data (the record) | `/srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/YYYY/MM/YYYY-MM-DD.csv` | UTC day files ([`DATA-FORMAT.md`](../DATA-FORMAT.md)) |
| Files made for OED | `/srv/arkan-monitoring/data/export/oed/adab/*.csv` | made by `manage.py export-oed`, WITA times |
| Backups | `/srv/arkan-monitoring/backups/` | `data-*.tar.gz` (ours), `oed-*.sql.gz` (OED database) |
| Caddy site file | `/opt/edge/sites/monitoring.caddy` | from [`server/deploy/oed/monitoring-oed.caddy`](../../server/deploy/oed/monitoring-oed.caddy) once OED is installed |
| Shared Arkan logins | `/opt/edge/secrets/hub-users.caddy` | owner only |
| OED image | `arkan-oed:v1.0.0` in the VPS's Docker | built on the laptop (A.3) |

| Container | Port (VPS loopback) | Memory limit | Role |
|---|---|---|---|
| `arkan-monitoring-ingest` | 127.0.0.1:8800 | 96 MB | our ingest service, live page, alarms |
| `arkan-oed-web` | 127.0.0.1:8810 (inside: 3000) | 320 MB | OED web |
| `arkan-oed-db` | none (Docker network only) | 256 MB | OED's PostgreSQL |
| (other services) | Hub 8780, CMMS 8790, Hermes | | not touched |

| Address | Who | Login |
|---|---|---|
| `https://arkan-monitoring.duckdns.org/` | people | Arkan login (Caddy), then OED's own login for admin pages |
| `https://arkan-monitoring.duckdns.org/live/` | people | Arkan login |
| `https://arkan-monitoring.duckdns.org/api/v1/ingest` and other device paths | the logger | device token, no web login |
| `http://127.0.0.1:8810/api/csv/readings` | `ai` on the VPS (curl), later the ingest service | OED user with the CSV role |

### 0.5 Who does what

| Task | Owner (with `sudo`, approves) | Operator (user `ai`, no `sudo`) |
|---|---|---|
| Build the image on the laptop, copy it to the VPS | | yes |
| Create `/srv/arkan-monitoring/oed*` folders | yes | |
| Write the secrets file, start the containers | | yes (in the `docker` group) |
| Copy the Caddy file, `caddy validate`, **reload Caddy** | yes, and approves the reload | prepares, asks |
| OED admin user, units, meters, groups | | yes |
| Export and upload data, view refresh, backups | | yes |
| Restart or remove containers of other services | never touched | never touched |
| OED upgrade | approves | does it |

---

## Part A: install OED on hermes-vps

### A.1 The OED version we pin, and why

"Pinning" means we always build the same OED code, named by a fixed tag, so the VPS never changes by surprise.

| | **v1.0.0 (pinned)** | `development` branch |
|---|---|---|
| What it is | The latest **release**. OED's website lists "oed version 1.0.0" as the current documentation (`_data/navigation.yml` of the website). No later tag was found (`v1.0.1`, `v1.1.0`, `v2.0.0` do not exist) | Work in progress, about two years newer. OED: "In general, production sites do not use this code" (help page *Installation Directions*, v1.0.0) |
| Node.js | `node:16.13.2` (`containers/web/Dockerfile`) | `node:18.17.1` |
| CSV upload login fields | `email`, `password` | `username` (or `email`), `password` |
| Meter field in CSV upload | `meterName` (matched against the meter's **Name**) | `meterIdentifier` (or `meterName`) |
| View refresh in CSV upload | `refreshReadings`, `refreshHourlyReadings` | `refreshReadings` only (refreshes both) |
| Graph types | Line, Bar, Compare, Map | also 3D and Radar |

**Decision: v1.0.0**, because it is OED's own advice for a production site (install page: "a site should take the latest release"), and because its CSV API and help pages match each other. Everything in this tutorial is for v1.0.0. When OED publishes a newer release, read its upgrade page and section E.4 before moving.

> Note: Node.js 16 no longer gets security updates. The risk is low here (OED is behind the Arkan login and on the loopback), but it is a reason to follow OED's next release.

### A.2 Check the VPS (before anything)

1. **VPS, user ai:** check the processor type.
   ```bash
   uname -m
   ```
   Expected: `x86_64`. If it says `aarch64`, the image must be built for ARM (A.3, step 4).

2. **VPS, user ai:** check free memory.
   ```bash
   free -h
   ```
   Expected: at least about 600 MB "available" for OED (web 320 MB and database 256 MB at most). If not, read [`VPS-MEMORY.md`](../VPS-MEMORY.md) "On the VPS itself" (swap) with the owner before going on.

3. **VPS, user ai:** see what the other containers use now.
   ```bash
   docker stats --no-stream
   ```
   Expected: a table with the Hub, CMMS, Hermes and `arkan-monitoring-ingest`. Write the numbers down (Appendix C).

4. **VPS, user ai:** check port 8810 is free.
   ```bash
   ss -ltn | grep -E ':8810\b'
   ```
   Expected: **no output**. If something is shown, pick another port and change it in `docker-compose.yml` (`127.0.0.1:8810:3000`) and in `monitoring-oed.caddy` (`127.0.0.1:8810`).

5. **VPS, user ai:** check disk space.
   ```bash
   df -h /srv /var/lib/docker
   ```
   Expected: at least 3 GB free. The image is about 1 GB (**to verify** after A.3), and the copy needs the same again for a short time.

### A.3 Build the lean image off the VPS

**Why not OED's own compose?** OED's `docker-compose.yml` runs `src/scripts/installOED.sh` at every start: `npm ci` (downloads and installs every package, build tools included) and `webpack build` (compiles the web pages). That takes 1 to 2 GB of RAM for minutes at each restart ([`VPS-MEMORY.md`](../VPS-MEMORY.md)). Our [`Dockerfile`](../../server/deploy/oed/Dockerfile) does those two steps **once, on another machine**, and keeps only what is needed to run: this is a **multi-stage build** (stage 1 builds, stage 2 is a small "slim" image that receives the result).

**Where to build: two ways.**

| | Laptop with Docker Desktop (**recommended now**) | GitHub Actions |
|---|---|---|
| What | You run `docker build` on your own computer | A GitHub workflow builds the image on GitHub's machines and stores it in a registry (GitHub Container Registry, `ghcr.io`) |
| Getting it to the VPS | `docker save` to a file, `scp`, `docker load` | `docker pull` on the VPS, after a one-time `docker login ghcr.io` with a read-only token |
| Needs | Docker Desktop, 4 GB of memory for Docker, 20 minutes | a workflow file in `.github/workflows/`, a registry, a token on the VPS (none of this exists yet) |
| Good for | the first install, rare upgrades | frequent upgrades, several people |

Use the laptop for now. GitHub Actions can come later if upgrades become frequent.

1. **Laptop:** install **Docker Desktop** (docker.com) and start it. In Docker Desktop, Settings, Resources, give Docker at least **4 GB** of memory (the webpack step needs it).

2. **Laptop (PowerShell):** go to your copy of this repository.
   ```powershell
   cd <repository folder>
   ```

3. **Laptop (PowerShell):** get the latest files (the reviewed deploy files must be there).
   ```powershell
   git pull
   ```

4. **Laptop (PowerShell):** build the image. It downloads OED v1.0.0 from GitHub and builds it.
   ```powershell
   docker build -t arkan-oed:v1.0.0 --build-arg OED_REF=v1.0.0 server/deploy/oed
   ```
   Expected: 5 to 20 minutes, ending with a line like `naming to docker.io/library/arkan-oed:v1.0.0`.
   - If your laptop has an Apple M processor (ARM) and the VPS is `x86_64`, use instead:
     ```powershell
     docker buildx build --platform linux/amd64 -t arkan-oed:v1.0.0 --build-arg OED_REF=v1.0.0 --load server/deploy/oed
     ```
   - If it stops with `JavaScript heap out of memory`: give Docker more memory (step 1) and run step 4 again.
   - If `npm ci` or `npm prune` fails: copy the error into an issue; do not change OED's code (**to verify** on the first build).

### A.4 Test the image on the laptop

1. **Laptop (PowerShell):** show the exact OED commit inside the image.
   ```powershell
   docker run --rm arkan-oed:v1.0.0 cat OED_COMMIT
   ```
   Expected: a 40-character commit id. Write it in Appendix C: it is what "pinned" means.

2. **Laptop (PowerShell):** check that the built web pages are there.
   ```powershell
   docker run --rm arkan-oed:v1.0.0 ls src/client/public/app
   ```
   Expected: `bundle.js` is listed (OED's `webpack.config.js` builds `src/client/public/app/bundle.js`).

3. **Laptop (PowerShell):** see the image size.
   ```powershell
   docker image ls arkan-oed
   ```
   Expected: one line `arkan-oed  v1.0.0  ...  <size>`. Write the size in Appendix C.

### A.5 Move the image to the VPS

1. **Laptop (PowerShell):** save the image to a file.
   ```powershell
   docker save -o arkan-oed-v1.0.0.tar arkan-oed:v1.0.0
   ```
   Expected: a file `arkan-oed-v1.0.0.tar` in the current folder.

2. **Laptop (PowerShell):** copy it to the VPS (`hermes-vps` is the SSH name used in [`VPS-SETUP.md`](../VPS-SETUP.md)).
   ```powershell
   scp arkan-oed-v1.0.0.tar hermes-vps:/home/ai/
   ```
   Expected: a progress bar to 100 %.

3. **VPS, user ai:** load it into Docker.
   ```bash
   docker load -i /home/ai/arkan-oed-v1.0.0.tar
   ```
   Expected: `Loaded image: arkan-oed:v1.0.0`.

4. **VPS, user ai:** delete the copied file.
   ```bash
   rm /home/ai/arkan-oed-v1.0.0.tar
   ```

5. **Laptop (PowerShell):** delete the local file too.
   ```powershell
   Remove-Item arkan-oed-v1.0.0.tar
   ```

### A.6 Get the deploy files on the VPS

The files of `server/deploy/oed/` reach the VPS with the repository, at a tag (as for the ingest service).

1. **VPS, user ai:** go to the code.
   ```bash
   cd /opt/arkan-monitoring
   ```

2. **VPS, user ai:** fetch the tags.
   ```bash
   git fetch --tags
   ```

3. **VPS, user ai:** check out the tag that contains the reviewed OED files.
   ```bash
   git checkout <tag>
   ```

4. **VPS, user ai:** check the files are there.
   ```bash
   ls /opt/arkan-monitoring/server/deploy/oed
   ```
   Expected: `Dockerfile  docker-compose.yml  initdb  monitoring-oed.caddy  oed-backup.sh  oed.env.example  postgresql-oed.conf`.

### A.7 Folders and secrets

1. **VPS, owner with sudo:** create the two folders.
   ```bash
   sudo mkdir -p /srv/arkan-monitoring/oed /srv/arkan-monitoring/oed-postgres
   ```

2. **VPS, owner with sudo:** give the secrets folder to `ai`.
   ```bash
   sudo chown ai:ai /srv/arkan-monitoring/oed
   ```

3. **VPS, owner with sudo:** make it private.
   ```bash
   sudo chmod 700 /srv/arkan-monitoring/oed
   ```
   Leave `oed-postgres` as it is: the PostgreSQL container sets its owner at the first start.

   > **Warning.** `server/deploy/setup-vps.sh --apply` runs `chown -R 1000:1000 /srv/arkan-monitoring`. Run again after OED is installed, it would also change the owner of the database files and **PostgreSQL would stop starting**. Do not run it again without asking (Part F has the repair).

4. **VPS, user ai:** copy the example secrets file.
   ```bash
   cp /opt/arkan-monitoring/server/deploy/oed/oed.env.example /srv/arkan-monitoring/oed/oed.env
   ```

5. **VPS, user ai:** make it readable by `ai` only.
   ```bash
   chmod 600 /srv/arkan-monitoring/oed/oed.env
   ```

6. **VPS, user ai:** make a random value. Run it **three times**, one value for each line of the file.
   ```bash
   openssl rand -hex 24
   ```
   Expected: 48 characters, letters `a` to `f` and digits only (no special character that could break the file).

7. **VPS, user ai:** open the file and replace the three `<...>` with the three values.
   ```bash
   nano /srv/arkan-monitoring/oed/oed.env
   ```
   Save with Ctrl+O, Enter, and leave with Ctrl+X. Copy the three values to the password manager.

   | Line | What it is |
   |---|---|
   | `POSTGRES_PASSWORD` | password of the PostgreSQL superuser `postgres` |
   | `OED_DB_PASSWORD` | password of the database user `oed` that OED uses. **Never change it after the first start**: the database keeps the first one (OED's `docker-compose.yml` comments say the same) |
   | `OED_TOKEN_SECRET` | signs OED's login tokens |

### A.8 First start

1. **VPS, user ai:** go to the OED deploy folder. The next commands of A.8 and A.9 run from here.
   ```bash
   cd /opt/arkan-monitoring/server/deploy/oed
   ```

2. **VPS, user ai:** start the database only.
   ```bash
   docker compose up -d database
   ```
   Expected: `Container arkan-oed-db  Started`. On this first start, the script `initdb/10-oed-user.sh` creates the user `oed` and the database `oed` (the same as OED's `containers/database/init.sql`, with our password).

3. **VPS, user ai:** wait 30 seconds, then check its state.
   ```bash
   docker compose ps
   ```
   Expected: `arkan-oed-db ... Up ... (healthy)`.

4. **VPS, user ai:** read its log.
   ```bash
   docker compose logs database --tail 40
   ```
   Expected: `CREATE ROLE`, `CREATE DATABASE` and, at the end, `database system is ready to accept connections`. If you see `permission denied` on the data folder, see Part F.

5. **VPS, user ai:** start OED web.
   ```bash
   docker compose up -d web
   ```
   Expected: `Container arkan-oed-web  Started`. At start it runs `npm run createdb` (creates OED's tables, standard units and conversions the first time) and then OED itself.

6. **VPS, user ai:** read its log.
   ```bash
   docker compose logs web --tail 40
   ```
   Expected: the end shows `Listening on port 3000` (the line OED's help page *Install Output* shows). If it shows `password authentication failed for user "oed"`, the `OED_DB_PASSWORD` changed after the database was created: see Part F.

7. **VPS, user ai:** ask OED for its version.
   ```bash
   curl -s http://127.0.0.1:8810/api/version
   ```
   Expected: a short text with the version, for example `"1.0.0"` (OED's `src/server/routes/version.js`; exact text **to verify**).

### A.9 Create the OED admin user

OED has its **own users**, separate from the Arkan login. The first one is an **admin** (all rights). It is created from the command line (OED help page *Installation Directions*); OED's page uses `docker compose run`, which starts a second container: we use `exec`, which runs inside the container already running (less memory).

1. **VPS, user ai**, in `/opt/arkan-monitoring/server/deploy/oed`: start the user creation.
   ```bash
   docker compose exec web npm run createUser
   ```
   It asks `Email of user to create:` then `Password:`. The email must look like an email (it is checked) but does not need to receive mail: use `<oed-admin-email>`. The password needs at least 8 characters (`src/server/services/user/createUser.js`). **What you type is shown on the screen.**
   Expected: `User <oed-admin-email> created`.

2. **VPS, user ai:** clear the screen so the password does not stay visible.
   ```bash
   clear
   ```
   Copy the email and password to the password manager as "OED admin".

### A.10 Caddy: OED at `/`, our service keeps `/live/` and `/api/v1/`

**What changes.** The new site file [`monitoring-oed.caddy`](../../server/deploy/oed/monitoring-oed.caddy) replaces [`server/deploy/monitoring.caddy`](../../server/deploy/monitoring.caddy):
- the logger paths are unchanged (no web login, the device token is checked by our service);
- `/live`, `/live/...`, `/api/v1/...` and `/health` go to our service, behind the Arkan login;
- **everything else goes to OED**, behind the Arkan login. The old line `redir / /live/` is gone.

**Why there is no collision.** OED's server only uses `/api/<name>` paths (`/api/users`, `/api/meters`, `/api/readings`, `/api/csv`, `/api/version`...), its page routes (`/login`, `/admin`, `/graph`, `/meters`, `/groups`, `/maps`, `/users`, `/csv`, `/units`, `/conversions`...) and static files. It never uses `/api/v1`, `/live` or `/health` (`src/server/app.js`, v1.0.0).

**Two logins.** First the browser asks for the **Arkan login** (Caddy `basicauth`, the shared file `hub-users.caddy`). Then, inside OED, only the admin pages need the **OED login** (A.9). They do not fight: OED sends its own login in a header named `token`, not in the `Authorization` header that Caddy uses (`src/client/app/utils/api/ApiBackend.ts`, `src/server/routes/authenticator.js`). Caddy removes the Arkan `Authorization` header before passing requests to OED.

**OED's CSV upload API (`/api/csv/...`).** PLAN.md section 5.4 says it should not be published. But OED's own CSV page in the browser uses this same API, so blocking it in Caddy also breaks that page. The draft keeps it behind the Arkan login (and it also needs an OED user with the CSV role). A commented block in the file blocks it if the owner prefers. From the VPS, `curl` and the future push reach OED directly on `127.0.0.1:8810`, without Caddy.

1. **VPS, owner with sudo:** keep a copy of the current site file, outside the `sites` folder (Caddy imports `/opt/edge/sites/*.caddy`).
   ```bash
   sudo cp /opt/edge/sites/monitoring.caddy /opt/edge/monitoring.caddy.before-oed
   ```

2. **VPS, owner with sudo:** put the new file in place.
   ```bash
   sudo cp /opt/arkan-monitoring/server/deploy/oed/monitoring-oed.caddy /opt/edge/sites/monitoring.caddy
   ```

3. **VPS, owner with sudo:** check the whole Caddy configuration.
   ```bash
   sudo caddy validate --config /etc/caddy/Caddyfile
   ```
   Expected: `Valid configuration`. If not, put the old file back and stop here:
   ```bash
   sudo cp /opt/edge/monitoring.caddy.before-oed /opt/edge/sites/monitoring.caddy
   ```

4. **VPS, owner with sudo:** **the owner approves**, then reloads Caddy (no downtime for the other sites).
   ```bash
   sudo systemctl reload caddy
   ```

5. **Laptop (PowerShell):** the home page must ask for a login.
   ```powershell
   curl.exe -s -o NUL -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/
   ```
   Expected: `401`.

6. **Laptop (PowerShell):** a logger path must reach our service without the web login.
   ```powershell
   curl.exe -s https://arkan-monitoring.duckdns.org/api/v1/ota
   ```
   Expected: `{"ok": false, "error": "unknown or missing device token"}` (the answer of our service, not of Caddy).

7. **Laptop, browser:** open `https://arkan-monitoring.duckdns.org/` and sign in with your Arkan login.
   Expected: OED's main graph page (empty for now).

8. **Laptop, browser:** open `https://arkan-monitoring.duckdns.org/live/`.
   Expected: our live page, as before.

### A.11 First login to OED and site settings

1. **Browser:** in OED, open **Options** (top right) and click **Log in** (OED help page *Installation Directions*). On a narrow window the menu is called **Page choices & login**. Sign in with `<oed-admin-email>`.
   Expected: the **Pages** menu now shows admin choices (Admin Panel, Meters, Groups, Units, Conversions, Maps, CSV).

2. **Browser:** **Pages**, **Admin Panel** (help page *Site Settings*). Set:

   | Setting | Value | Why |
   |---|---|---|
   | Default Site Title | `Arkan monitoring` | shown at the top of each page |
   | Default Graph Type | Line | |
   | Default Language | English | |
   | Default Time Zone | `Asia/Makassar` | OED: "not a bad idea to set this to the local time zone"; WITA has no daylight saving |
   | Default meter reading frequency | leave `00:15:00` | we set it on each meter (B.5) |

   Click **Submit**. Expected: a short "saved" notice.

### A.12 Scheduled view refresh (cron)

OED does not draw long graphs from every reading. It keeps **hourly and daily summaries** (PostgreSQL "materialized views") and refreshes them on a schedule. OED's scripts (`src/scripts/refreshReadingViewsCron.bash`, `refreshHourlyReadingViewsCron.bash`) use `docker compose run --rm web ...`, which starts a **second** web container each time. We run the same `npm` script **inside the running container** with `docker exec` instead ([`VPS-MEMORY.md`](../VPS-MEMORY.md)).

1. **VPS, user ai:** check the server clock's time zone.
   ```bash
   date
   ```
   Expected: a time ending in `UTC`. The times below assume UTC; WITA is UTC + 8.

2. **VPS, user ai:** open the crontab of `ai`.
   ```bash
   crontab -e
   ```
   Add these lines (hourly refresh at minute 05; daily refresh at 16:25 UTC = 00:25 WITA, after the WITA day ends; OED database backup at 02:40 UTC, see E.2):
   ```text
   5 * * * * docker exec arkan-oed-web npm run --silent refreshHourlyReadingViews >/dev/null 2>&1
   25 16 * * * docker exec arkan-oed-web npm run --silent refreshReadingViews >/dev/null 2>&1
   40 2 * * * /opt/arkan-monitoring/server/deploy/oed/oed-backup.sh >> /srv/arkan-monitoring/backups/backup.log 2>&1
   ```
   Expected: `crontab: installing new crontab`.

### A.13 Check the RAM against the plan

1. **VPS, user ai:** measure.
   ```bash
   docker stats --no-stream arkan-oed-web arkan-oed-db arkan-monitoring-ingest
   ```
   Expected, from [`VPS-MEMORY.md`](../VPS-MEMORY.md):

   | Container | Expected | Limit |
   |---|---|---|
   | `arkan-oed-web` | 150 to 250 MB | 320 MB |
   | `arkan-oed-db` | 80 to 150 MB | 256 MB |
   | `arkan-monitoring-ingest` | 25 to 40 MB | 96 MB |
   | Total | 300 to 450 MB | |

2. **VPS, user ai:** check what is left for the other services.
   ```bash
   free -h
   ```
   Expected: "available" still comfortable for the Hub, the CMMS and Hermes. Write the numbers in Appendix C and send them for [`VPS-MEMORY.md`](../VPS-MEMORY.md). Measure again after the first data load (Part C) and during a view refresh: the refresh runs inside the web container and counts against its 320 MB (**to verify** that it fits; see E.6).

---

## Part B: set up Adab in OED

All of Part B is done in the browser, logged in to OED as the admin (A.11).

### B.1 Units and conversions, simply

OED never graphs a number without a **unit**. Each unit has (help pages *Conversion & Unit*, *Unit Creating*, *Standard Units*):
- a **type**: `unit` (a unit people graph in, like kWh or Celsius), `meter` (the unit a meter "collects in"; never shown to people), or `suffix` (special, not used here);
- what it **represents**: `quantity` (can be added up: kWh), `flow` (a rate: kW), or `raw` (neither added nor a rate: it is **averaged**, like a temperature);
- **displayable**: `all` (everyone can graph in it), `admin`, or `none`.

A **conversion** links two units with a straight line: `destination = slope x source + intercept`. A meter's own unit must be of type `meter`, and a conversion must go from it to a graphing unit. OED's own example is a meter unit `Temperature_Fahrenheit` that converts to Fahrenheit and then to Celsius.

What OED v1.0.0 creates by itself (help page *Standard Units*):

| Unit | Type | Represents | Displayable at install | Conversion |
|---|---|---|---|---|
| kWh | unit | quantity | yes | |
| Electric_Utility | meter | quantity | no | Electric_Utility to kWh, slope 1, one way |
| Celsius | unit | raw | **no** | Celsius to Fahrenheit, both ways |
| Fahrenheit | unit | raw | no | |
| (BTU, m³ gas, kg, metric ton, gallon, liter) | unit | quantity | no | |

So for Adab:
- **energy**: meter unit `Electric_Utility` (exists), graphed in `kWh` (exists);
- **temperature**: a new meter unit, converted to `Celsius` (exists, must be made visible);
- **humidity**: a new meter unit and a new graphing unit `% RH`;
- optional **current, voltage, power factor**: a meter unit and a graphing unit for each.

Saving a unit or a conversion reloads OED's main page (help page *Unit Creating*, "Details"). Go back to the page after each save.

### B.2 Make Celsius visible

1. **Browser:** **Pages**, **Units**. Find the **Celsius** card and click **Edit Unit**.
2. Set **Displayable** to `all`. Click **Save all**.
   Expected: OED reloads; Celsius now appears in the units menu of the graph page.

### B.3 Create the units

**Browser:** **Pages**, **Units**, **Create a Unit**, once per line. Leave Preferred Display `yes`, Sec in Rate `3600` (not used for raw units), Suffix empty.

| Identifier | Name | Type of Unit | Unit Represent | Displayable | Note |
|---|---|---|---|---|---|
| `% RH` | `percent relative humidity` | unit | raw | all | graphing unit for humidity |
| `Temperature_Sensor_C` | `Temperature_Sensor_C` | meter | raw | none | meter unit of the TH temperature meters (collect in Celsius) |
| `Humidity_Sensor_RH` | `Humidity_Sensor_RH` | meter | raw | none | meter unit of the TH humidity meters |
| optional `A` | `ampere` | unit | raw | all | phase current |
| optional `Current_Sensor_A` | `Current_Sensor_A` | meter | raw | none | |
| optional `V` | `volt` | unit | raw | all | phase voltage |
| optional `Voltage_Sensor_V` | `Voltage_Sensor_V` | meter | raw | none | |
| optional `PF` | `power factor` | unit | raw | all | |
| optional `PF_Sensor` | `PF_Sensor` | meter | raw | none | |

Expected after each save: the new unit card on the Units page.

### B.4 Create the conversions

**Browser:** **Pages**, **Conversions**, **Create a Conversion**, once per line. OED's rules (help page *Conversion & Unit*): a meter unit is only ever the **source**; never convert between raw and quantity units.

| Source | Destination | Bidirectional | Slope | Intercept |
|---|---|---|---|---|
| `Temperature_Sensor_C` | `Celsius` | no | 1 | 0 |
| `Humidity_Sensor_RH` | `% RH` | no | 1 | 0 |
| optional `Current_Sensor_A` | `A` | no | 1 | 0 |
| optional `Voltage_Sensor_V` | `V` | no | 1 | 0 |
| optional `PF_Sensor` | `PF` | no | 1 | 0 |

`Electric_Utility` to `kWh` already exists. Expected after each save: the conversion card on the Conversions page.

### B.5 Create the meters

In OED a **meter** is one series of readings. We use **one OED meter per value** (PLAN.md section 5.3). The **Name** must be **exactly** the name our exporter writes (`oed_meter_name()` in [`server/tools/manage.py`](../../server/tools/manage.py)): in v1.0.0 the CSV upload finds the meter by its Name (`Meter.getByName` in `src/server/services/csvPipeline/uploadReadings.js`). Use the same text as **Identifier** (the label people see in graphs); it also keeps the names right if we ever move to a version that uses the identifier.

**Browser:** **Pages**, **Meters**, **Create a Meter**, once per line of the first table, with the common settings of the second table.

| Name and Identifier | Unit | Default Graphic Unit | Reading Frequency | Cumulative | Reading Gap (s) | Reading Variation (s) | Note |
|---|---|---|---|---|---|---|---|
| `adab-EM01-energy` | Electric_Utility | kWh | `00:01:00` | **yes** | 3600 | 0 | main meter EM01, cumulative import counter `EM01_e` |
| `adab-TH1-temp` | Temperature_Sensor_C | Celsius | `00:05:00` | no | 3600 | 3600 | electrical room, 5-minute mean |
| `adab-TH1-hum` | Humidity_Sensor_RH | % RH | `00:05:00` | no | 3600 | 3600 | electrical room |
| `adab-TH2-temp` | Temperature_Sensor_C | Celsius | `00:05:00` | no | 3600 | 3600 | outdoor (AM2301) |
| `adab-TH2-hum` | Humidity_Sensor_RH | % RH | `00:05:00` | no | 3600 | 3600 | outdoor |
| optional `adab-EM01-i1`, `-i2`, `-i3` | Current_Sensor_A | A | `00:01:00` | no | 3600 | 0 | needs `export-oed --all` |
| optional `adab-EM01-v1`, `-v2`, `-v3` | Voltage_Sensor_V | V | `00:01:00` | no | 3600 | 0 | needs `export-oed --all` |
| optional `adab-EM01-pf` | PF_Sensor | PF | `00:01:00` | no | 3600 | 0 | needs `export-oed --all` |

The optional names are **lower case** (`adab-EM01-i1`), because that is what the exporter writes for the column `EM01_i1`.

| Common setting | Value | Why (help page *Meter Creating*) |
|---|---|---|
| Updates | no | OED does not fetch data itself; we upload |
| Displayable | yes | everyone can graph it (no = admins only) |
| Type | OTHER | not a meter brand OED reads directly |
| URL | empty | |
| GPS | `<latitude>,<longitude>` of the hotel | only needed for maps |
| Area, Area Unit | empty, no unit | |
| Cumulative Reset | no | a counter that goes down is an error to look at (alarm A19), not a reset |
| End Only Time | no | our files have a start and an end time |
| Reading Duplication | 1 | |
| Time Sort | increasing | |
| Time Zone | empty | uses the site default (A.11) |
| Start/End Time Stamp, Reading, Previous End Time Stamp | empty | OED fills them at each upload |

**Why Reading Gap 3600 on the energy meter.** For a cumulative meter, OED computes each reading as "this counter value minus the previous one". If the start of a reading is further from the end of the previous one than the Reading Gap, OED **drops** that reading (help page *Reading Import*, "The end of the previous reading is too far from the start of the next readings in cumulative data so drop this reading"). With the default of 0, one missing minute (logger reboot, a failed meter read) loses the energy of that minute and of the gap in OED's totals. With 3600 seconds, the kWh stay right, but the whole gap's energy is drawn in one minute (a short spike on the kW line). See the open point on the exporter in Appendix C.

**Why Reading Gap and Variation 3600 on the sensor meters.** For non-cumulative meters, gaps and changing lengths only make **warnings**. Our sensor readings normally last 5 minutes, but longer after a gap. The values only avoid a long list of warnings.

Expected after each save: the meter card on the Meters page, with its unit.

### B.6 Groups: what OED allows

A **group** adds up meters (and other groups). OED only allows meters in a group if **all of them share at least one unit** they can be graphed in; others are greyed out and cannot be selected (help page *Group Creating*: "Library Temperature is displayed this way because it is collecting in a temperature unit"). So **temperature and humidity cannot go in the same group as energy**. Adding up temperatures would make no sense anyway.

| Group name | Default Graphic Unit | Displayable | Child meters | Child groups | GPS |
|---|---|---|---|---|---|
| `adab` | kWh | yes | `adab-EM01-energy` (later: the other energy meters of the site) | none | `<latitude>,<longitude>` |
| `All sites` | kWh | yes | none | `adab` (later: each site group) | empty |

**Browser:** **Pages**, **Groups**, **Create a Group**, once per line. Click **Save all**.
Expected: two group cards. Temperature and humidity are shown together simply by selecting several meters on the graph page (Part D).

### B.7 Map (optional, later)

OED maps are an image you upload (a site plan, a city map) and calibrate with GPS points; meters and groups with a GPS value then show as circles on it (help page *Map Creating*: **Pages**, **Maps**, **Create a Map**). With one site, a map adds little. Make one when there are several sites.

### B.8 Checklist

| Item | Done |
|---|---|
| Celsius displayable `all` | |
| Units `% RH`, `Temperature_Sensor_C`, `Humidity_Sensor_RH` | |
| Conversions to Celsius and `% RH` | |
| Meters `adab-EM01-energy`, `adab-TH1-temp`, `adab-TH1-hum`, `adab-TH2-temp`, `adab-TH2-hum` | |
| Energy meter: Cumulative yes, Reading Gap 3600 | |
| Groups `adab` and `All sites` | |
| Optional units and meters for A, V, PF | |

---

## Part C: load data into OED

Until the automatic push exists, loading is done by hand: **export** with our tool, then **upload** with OED's CSV API (or its CSV page), then **refresh** OED's views.

### C.1 Rules to know first

- **UTC files, WITA times.** Our day files are UTC days. `--from` and `--to` of the exporter name those **UTC** days. The times written in the export files are **WITA** (UTC + 8), because OED stores times without a time zone (help page *Time*) and we want 08:00 in OED to mean 08:00 at the hotel. So `--from 2026-11-08 --to 2026-11-08` gives the readings from **08:00 WITA on 8 November to 08:00 WITA on 9 November**.
- **Complete days only.** Export a UTC day only after it has ended **and** the logger has sent everything (no backlog, any SD card backfill done). OED cannot take older readings in the middle of a cumulative meter later (C.8).
- **Each day once, in order.** For non-cumulative meters, a reading with the same start time as one already in OED makes OED **reject the whole file** unless `update=yes` (help page *Reading Import*, "update"). For the energy meter, a reading older than the last one is **dropped**.
- **Our files need `headerRow=yes` and `gzip=no`.** OED's default for `gzip` is **yes** (help page *Reading Import*), and our files are plain CSV.
- **Column order matches.** OED reads the columns by position: reading, start time, end time (`processData.js` uses `rows[i][0]`, `[1]`, `[2]`). Our exporter writes `reading,start_timestamp,end_timestamp`, the header OED's help page shows, and times as `YYYY-MM-DD HH:MM:SS`, OED's "canonical format".

### C.2 The CSV user and its password file (once)

The upload needs an OED user with the **CSV** role (or admin) in the request: fields `email` and `password` (help page *CSV import*; `src/server/routes/csv.js` checks them with `verifyCredentials` before it accepts the file). A user that can only upload is safer than the admin.

1. **Browser, OED admin:** **Pages**, **Admin Panel**, **Users**, **Create a User**. Email `<csv-user-email>`, a long password, Role **CSV**. Click **Submit new user** (help page *User*).
   Expected: the new user in the list with role CSV. Copy email and password to the password manager as "OED CSV".

2. **VPS, user ai:** create an empty file that only `ai` can read.
   ```bash
   install -m 600 /dev/null /home/ai/.oed-csv-password
   ```

3. **VPS, user ai:** type the password without showing it (type it, then press Enter).
   ```bash
   read -rs OED_CSV_PW
   ```

4. **VPS, user ai:** write it to the file, with no line end.
   ```bash
   printf '%s' "$OED_CSV_PW" > /home/ai/.oed-csv-password
   ```

5. **VPS, user ai:** forget it in the shell.
   ```bash
   unset OED_CSV_PW
   ```
   `curl -F 'password=</home/ai/.oed-csv-password'` reads the field from this file, so the password never appears in a command line or in the shell history.

### C.3 Export from our data

1. **VPS, user ai:** check the logger is up to date (last record recent).
   ```bash
   docker exec arkan-monitoring-ingest python tools/manage.py list
   ```
   Expected: `LOG-0001: fw ..., last record 2026-11-09T...` (a time after the end of the day you want).

2. **VPS, user ai:** export one UTC day (here 8 November 2026).
   ```bash
   docker exec arkan-monitoring-ingest python tools/manage.py export-oed adab --from 2026-11-08 --to 2026-11-08
   ```
   Expected: `5 file(s) in /data/export/oed/adab (header row: yes; *-energy files: cumulative=yes)`. `/data` in the container is `/srv/arkan-monitoring/data` on the VPS. Each export **replaces** the files of the folder. Add `--all` for every value (V, A, PF... one file each); upload only those that have a meter in OED.

3. **VPS, user ai:** list the files.
   ```bash
   ls -l /srv/arkan-monitoring/data/export/oed/adab/
   ```
   Expected: `adab-EM01-energy.csv`, `adab-TH1-temp.csv`, `adab-TH1-hum.csv`, `adab-TH2-temp.csv`, `adab-TH2-hum.csv`. A file is missing if the sensor had no valid value that day.

4. **VPS, user ai:** look at the first lines.
   ```bash
   head -3 /srv/arkan-monitoring/data/export/oed/adab/adab-EM01-energy.csv
   ```
   Expected (values are examples):
   ```text
   reading,start_timestamp,end_timestamp
   184523.17,2026-11-08 08:00:00,2026-11-08 08:01:00
   184523.65,2026-11-08 08:01:00,2026-11-08 08:02:00
   ```
   The first time starts at **08:00**: WITA for 00:00 UTC. If it starts at 00:00, the times are UTC and must not be uploaded (Part F).

### C.4 Upload with curl from the VPS (recommended)

The request goes straight to OED on the loopback (`127.0.0.1:8810`), not through Caddy, so no Arkan login is needed. Parameters from the help page *Reading Import* (v1.0.0) and `validateCsvUploadParams.js`:

| Parameter | Energy file | Temperature and humidity files | Meaning |
|---|---|---|---|
| `email`, `password` | CSV user | CSV user | must come **before** `csvfile` (`csv.js` checks them when the file arrives) |
| `meterName` | `adab-EM01-energy` | the file name without `.csv` | the meter's Name in OED |
| `headerRow` | yes | yes | our files have a header line |
| `gzip` | no | no | default is yes |
| `cumulative` | **yes** | no | energy is the meter's running counter |
| `cumulativeReset` | no | (not sent) | a counter going down is rejected |
| `update` | (not sent, = no) | (not sent, = no) | yes would replace existing readings |
| `refreshReadings`, `refreshHourlyReadings` | (not sent) | (not sent) | we refresh once at the end (C.6) |
| `csvfile` | `@<path>` | `@<path>` | the file; **always the last field** |

1. **VPS, user ai:** upload the energy file.
   ```bash
   curl -sS -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8810/api/csv/readings \
     -F 'email=<csv-user-email>' \
     -F 'password=</home/ai/.oed-csv-password' \
     -F 'meterName=adab-EM01-energy' \
     -F 'headerRow=yes' \
     -F 'gzip=no' \
     -F 'cumulative=yes' \
     -F 'cumulativeReset=no' \
     -F 'csvfile=@/srv/arkan-monitoring/data/export/oed/adab/adab-EM01-energy.csv'
   ```
   Expected:
   - normally `<h1>SUCCESS</h1>...` and `HTTP 200`;
   - **the very first upload to this meter**: `<h1>FAILURE</h1>` with "The first ever reading must be dropped when dealing with cumulative data" and `HTTP 500`. This is normal: OED needs a previous counter value, so it drops the first row and keeps all the others (help page *Reading Import*, "First reading ever seen by a meter").

2. **VPS, user ai:** upload the four sensor files (one command, a loop over the four meters).
   ```bash
   for m in adab-TH1-temp adab-TH1-hum adab-TH2-temp adab-TH2-hum; do curl -sS -w "\n$m: HTTP %{http_code}\n" -X POST http://127.0.0.1:8810/api/csv/readings -F 'email=<csv-user-email>' -F 'password=</home/ai/.oed-csv-password' -F "meterName=$m" -F 'headerRow=yes' -F 'gzip=no' -F 'cumulative=no' -F "csvfile=@/srv/arkan-monitoring/data/export/oed/adab/$m.csv"; done
   ```
   Expected: `<h1>SUCCESS</h1>` and `adab-TH1-temp: HTTP 200`, and the same for the three others. Warnings about gaps or length may appear in the text: they are only warnings.

3. If you see `Invalid credentials`, `not found`, `unexpected argument` or another FAILURE: Part F.

### C.5 Or upload with OED's CSV page (no curl)

Useful for a one-off file or to see the options.

1. **Laptop (PowerShell):** copy the files to the laptop.
   ```powershell
   scp "hermes-vps:/srv/arkan-monitoring/data/export/oed/adab/*.csv" .
   ```
   Expected: the five files in the current folder.

2. **Browser, OED login (admin or CSV user):** **Pages**, **CSV**, tab **Readings** (help page *CSV import*).

3. Fill in, for each file:

   | Field on the page | Energy file | Sensor files |
   |---|---|---|
   | Meter name | `adab-EM01-energy` | `adab-TH1-temp` (etc.) |
   | Cumulative | yes | no |
   | Cumulative Reset | no | meter value or default |
   | Gzip | **unticked** | **unticked** |
   | Header Row | **ticked** | **ticked** |
   | Create Meter, Update | unticked | unticked |
   | Refresh Daily Readings, Refresh Hourly Readings | tick them on the **last** file only | |
   | CSV File | choose the file | choose the file |

4. Click **Submit CSV Data**.
   Expected: a window starting with `SUCCESS`. Click **OK**. Reload the browser page to see the new data (help page *CSV import*).

### C.6 Refresh OED's views and check a graph

1. **VPS, user ai:** refresh the daily and hourly views (`npm` script of OED's `package.json`).
   ```bash
   docker exec arkan-oed-web npm run --silent refreshAllReadingViews
   ```
   Expected: returns after a few seconds with no error.

2. **Browser:** reload OED. On the graph page choose **Line**, select the meter `adab-EM01-energy`, unit **kWh**.
   Expected: a line over the day. With the rate **Hour** (the default), kWh per hour is **kW**: the line is the power.

3. **Browser:** select `adab-TH1-temp` and `adab-TH2-temp`, unit **Celsius**.
   Expected: two temperature lines.

### C.7 The next days, without duplicates

Each day:
1. Wait until the UTC day has ended and the logger has sent everything (C.3 step 1).
2. Export **that day only** (C.3 step 2, with the new date).
3. Upload the five files (C.4).
4. Refresh the views (C.6 step 1).
5. Write a line in the load log below.

To see the last reading OED has for a meter: **Pages**, **Meters**, **Edit Meter** on its card: **End Time Stamp** is the end of the last reading received (help page *Meter Creating*). The next export must start right there.

| UTC day loaded | Loaded on | Energy result | Sensor results | By |
|---|---|---|---|---|
| 2026-11-08 | | | | |
| | | | | |

Several missing days at once: `--from <first day> --to <last day>` in one export, then one upload per meter.

### C.8 When something went wrong

- **A whole file was rejected** (FAILURE, no reading stored): OED did not move its "last reading" for that meter (help page *Reading Import*, "Using dropped readings as the previous reading"). Fix the cause and upload **the same file again before any later day**.
- **Wrong values in a temperature or humidity day already in OED:** export that day again and upload it with `-F 'update=yes'`: readings with the same start time are replaced (help page *Reading Import*, "update").
- **Energy day already in OED that must change:** a re-upload is refused (the readings are older than the meter's last reading). Do not try other settings by guessing. The clean way is to rebuild the energy meter from our files (E.5) (**to verify** if OED offers a simpler way).

### C.9 What will change with the automatic push

The planned push in our ingest service (PLAN.md section 5.3) will do C.3, C.4 and C.6 every 5 minutes: it will send only the new rows of each meter, with the same parameters, remember per meter the last time sent, and refresh the views. Part C then stays as the manual way to reload a period.

---

## Part D: use OED

Anyone with an Arkan login can look at the graphs; no OED login is needed for that (meters and groups are "Displayable: yes").

### D.1 Find your way

- **Graph type** buttons: **Line**, **Bar**, **Compare**, **Map**.
- **Groups** and **Meters** menus: pick one or more.
- **Units** menu: the unit to graph in (kWh, Celsius, % RH...). Only units that fit the selection can be chosen.
- **Rate** (line graph, quantity units only): Second, Minute, Hour, Day (help page *Rate*).
- **Options**: language, log in.

### D.2 Power (kW) with the line graph

1. Choose **Line**, the group `adab` (or the meter `adab-EM01-energy`), unit **kWh**, rate **Hour**.
   Result: kWh per hour = **kW**, over time.
2. Zoom by dragging on the graph. Click **Redraw** to load more detail for the zoomed time, **Restore** to go back (help page *Line Graphic*).
   OED shows at most 1,440 points per line: over a long period it shows **daily** or **hourly** averages; zoomed in enough, the original 1-minute readings (help page *Line Graphic*, "Redraw and Restore"). A peak of a few minutes is only visible when zoomed in.

### D.3 Energy (kWh) per day or week with the bar graph

1. Choose **Bar**, the group `adab`, unit **kWh**.
2. **Bar Interval**: **Day**, **Week** or **4 Weeks**, or the slider for 1 to 365 days (help page *Bar Graphic*).
   Result: one bar per day (or week) with its kWh. The time range is the one of the line graph.

### D.4 This week against last week with Compare

1. Choose **Compare**, the group `adab`.
2. Pick **Day**, **Week** or **4 Weeks** (help page *Compare Graphic*).
   Result: two bars, "last period so far" and "this period so far", and the change in %, red if usage went up. Weeks start on **Sunday** at midnight.
   "Now" is taken from **your computer's clock** (`moment()` in `src/client/app/actions/graph.ts`). On a computer set to WITA it matches the data; on a computer in another time zone, "today" is shifted (**to verify** in the browser).

### D.5 Temperature and humidity

- **Line** graph, meters `adab-TH1-temp` and `adab-TH2-temp`, unit **Celsius** (or Fahrenheit): room against outdoor.
- Meters `adab-TH1-hum` and `adab-TH2-hum`, unit **% RH**.
- **Bar** and **Compare** do not work for these "raw" units: OED shows "Cannot create bar graph on raw units such as temperature" (`src/client/app/translations/data.js`, `BarChartContainer.ts`). This is OED's design, not a fault.
- The daily min and max of temperature are in our `daily.csv` (`manage.py daily adab`), not in OED.

### D.6 Export from OED

Under a line graph (help page *Exporting Data*):
- **Export graph data**: the points you see, one CSV file per meter or group.
- **Export graph meter data**: the original readings behind the graph (meters only). Large exports may need an OED user with the EXPORT role.

The exported files use the same "reading, start, end" layout and can be uploaded again.

### D.7 What the times mean

- **Every time shown in OED is WITA** (hotel time), because we send WITA times and OED shows times as they were stored, whoever looks and wherever they are (help page *Time*).
- A day bar from 00:00 to 24:00 is a **WITA** day.
- Our own files and the live page use UTC in the files; the live page shows local time. 08:00 WITA = 00:00 UTC.

---

## Part E: maintenance

### E.1 View refresh

- Hourly and daily refresh run from the crontab of `ai` (A.12).
- After loading data by hand: C.6 step 1.
- To check the crontab:
  **VPS, user ai:**
  ```bash
  crontab -l
  ```
  Expected: the three lines of A.12.

### E.2 Backup of OED's database

[`oed-backup.sh`](../../server/deploy/oed/oed-backup.sh) runs `pg_dump` (a full SQL copy of the database, the command OED's *Upgrades* help page uses) inside the database container, compresses it and keeps the last 14, next to our data backups. It runs at 02:40 UTC (A.12).

1. **VPS, user ai:** run it once by hand.
   ```bash
   /opt/arkan-monitoring/server/deploy/oed/oed-backup.sh
   ```
   Expected: `... oed backup ok: /srv/arkan-monitoring/backups/oed-20261108T0240Z.sql.gz (<size>)`.

2. **VPS, user ai:** list the backups.
   ```bash
   ls -lh /srv/arkan-monitoring/backups/
   ```
   Expected: `data-*.tar.gz` (ours) and `oed-*.sql.gz`.

The OED database can also be rebuilt from our files (E.5), but a dump keeps the units, meters, groups, users and settings, which saves an hour of clicking.

### E.3 Restore a backup

**to verify**: test this once on a laptop before it is ever needed.

1. **VPS, user ai**, in `/opt/arkan-monitoring/server/deploy/oed`: stop OED web.
   ```bash
   docker compose stop web
   ```

2. **VPS, user ai:** delete the current OED database.
   ```bash
   docker exec arkan-oed-db psql -U postgres -c "DROP DATABASE oed;"
   ```
   Expected: `DROP DATABASE`.

3. **VPS, user ai:** create it again, empty.
   ```bash
   docker exec arkan-oed-db psql -U postgres -c "CREATE DATABASE oed WITH OWNER oed;"
   ```
   Expected: `CREATE DATABASE`.

4. **VPS, user ai:** load the chosen dump into it.
   ```bash
   gunzip -c /srv/arkan-monitoring/backups/oed-<stamp>.sql.gz | docker exec -i arkan-oed-db psql -U oed -d oed
   ```
   Expected: many lines (`CREATE TABLE`, `COPY ...`) and no `ERROR`.

5. **VPS, user ai:** start OED web.
   ```bash
   docker compose start web
   ```

6. **VPS, user ai:** refresh the views.
   ```bash
   docker exec arkan-oed-web npm run --silent refreshAllReadingViews
   ```
   Expected: graphs as on the day of the dump. Load the days after it again (Part C).

### E.4 Upgrade OED

OED's way (help page *Upgrades*): back up, check out the new tag, `npm ci`, migrate the database (`npm run migratedb -- highest`, in `src/scripts/updateOED.sh`), build, refresh all views. Ours does the same with a new image.

1. Read the release notes and the *Upgrades* help page of the **new** version. Some versions need extra steps.
2. **Laptop:** build the new image as in A.3 with the new tag, for example `--build-arg OED_REF=<new tag>` and `-t arkan-oed:<new tag>`. If OED changed its Node.js version (`containers/web/Dockerfile` of the new tag), also pass `--build-arg NODE_TAG=<that version>`.
3. Move it to the VPS (A.5).
4. In the repository, change `image: arkan-oed:v1.0.0` in `server/deploy/oed/docker-compose.yml` to the new tag, have it reviewed, tag the repository, check it out on the VPS (A.6).
5. **VPS, user ai:** back up first.
   ```bash
   /opt/arkan-monitoring/server/deploy/oed/oed-backup.sh
   ```
6. **VPS, user ai**, in `/opt/arkan-monitoring/server/deploy/oed`: stop OED web.
   ```bash
   docker compose stop web
   ```
7. **VPS, user ai:** migrate the database with the new image (a short extra container, while web is stopped).
   ```bash
   docker compose run --rm web npm run migratedb -- highest
   ```
   Expected: messages about migrations, no error.
8. **VPS, user ai:** start the new web.
   ```bash
   docker compose up -d web
   ```
9. **VPS, user ai:** refresh all views.
   ```bash
   docker exec arkan-oed-web npm run --silent refreshAllReadingViews
   ```
10. Check the version at the bottom of an OED page, a few graphs, and the CSV upload of the next day. **Check the CSV parameters of the new version**: they changed between v1.0.0 and `development` (A.1).
11. If it fails: put the old tag back in the compose file, `docker compose up -d web`, and restore the dump (E.3).

### E.5 Rebuild OED from our files (database lost)

Our day files are the record, so OED can always be rebuilt.

1. If a dump exists: restore it (E.3) and load the days after it (Part C). Stop here.
2. Without a dump: stop OED, empty the database folder, start again.
   **VPS, user ai**, in `/opt/arkan-monitoring/server/deploy/oed`:
   ```bash
   docker compose down
   ```
   **VPS, owner with sudo** (deletes OED's database for good):
   ```bash
   sudo rm -rf /srv/arkan-monitoring/oed-postgres/pgdata
   ```
   **VPS, user ai:**
   ```bash
   docker compose up -d
   ```
3. Redo A.9 (admin user), A.11 (settings), all of Part B, and C.2 (CSV user).
4. Export everything since the first day in one go (no `--to` means up to the last file).
   **VPS, user ai:**
   ```bash
   docker exec arkan-monitoring-ingest python tools/manage.py export-oed adab --from <first day>
   ```
5. Upload the five files (C.4) and refresh (C.6). A year is about 525,000 rows per energy file (1,440 a day); the upload can take minutes.

### E.6 RAM problems

1. **VPS, user ai:** see the use now.
   ```bash
   docker stats --no-stream arkan-oed-web arkan-oed-db
   ```
2. **VPS, user ai:** check if Docker stopped OED for lack of memory.
   ```bash
   docker inspect arkan-oed-web --format '{{.State.OOMKilled}} {{.RestartCount}}'
   ```
   Expected: `false 0`. `true` means the 320 MB limit was hit: the web restarted by itself.
3. Common causes and actions:

   | Cause | Action |
   |---|---|
   | View refresh or a large upload runs inside the web container, on top of OED | refresh at quiet hours (A.12); upload one file at a time; if it still hits the limit, raise `mem_limit` of `web` to 384m and tell the owner |
   | Long graphs with many meters | normal peaks; if OOM, keep `NODE_OPTIONS` at 192 and raise `mem_limit` a little |
   | PostgreSQL near 256 MB | lower `shared_buffers` to 32MB in `postgresql-oed.conf`, then `docker compose restart database` |
   | The VPS itself is short | [`VPS-MEMORY.md`](../VPS-MEMORY.md) "If RAM is still short": no per-phase meters in OED, lower limits, or OED on a second small VPS |

Every limit change goes through the repository (reviewed file), never by hand on the VPS only.

---

## Part F: troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Browser asks for a login again and again | wrong Arkan login | use the Arkan login from the password manager; the owner manages `hub-users.caddy` |
| `502` or blank page at `/` | OED web stopped or starting | `docker compose ps`, then `docker compose logs web --tail 50` (in the OED deploy folder) |
| `/live/` shows OED's page or `404` | old or wrong Caddy file | check `/opt/edge/sites/monitoring.caddy` is the OED variant; `caddy validate`; owner reloads |
| Logger uploads fail after the Caddy change | device paths changed | `curl.exe -s https://arkan-monitoring.duckdns.org/api/v1/ota` must answer our JSON (A.10 step 6); else put back the `.before-oed` file |
| `arkan-oed-db` restarts, log says `permission denied` or `data directory has wrong ownership` | `setup-vps.sh --apply` was run again and changed the owner | owner: `sudo chown -R 999:999 /srv/arkan-monitoring/oed-postgres/pgdata` (999 is the `postgres` user of the Debian image, **to verify** with `docker exec arkan-oed-db id postgres` when it runs) |
| Web log: `password authentication failed for user "oed"` | `OED_DB_PASSWORD` changed after the first start | put the first value back in `oed.env`, `docker compose up -d web` |
| Web log: `too many clients already` | more than 20 database connections | raise `max_connections` in `postgresql-oed.conf` to 30, restart the database |
| Upload: `<h1>FAILURE</h1>Error: Invalid credentials` | wrong password, or the user has no CSV role, or the password file ends with a line break | check the user's role on the Users page; rewrite the file with C.2 steps 3 to 5 |
| Upload: `QueryResultError ... No data returned from the query` with a `SELECT ... FROM users` | the email is not an OED user | check `<csv-user-email>` |
| Upload: `Meter with name '...' not found` | Name in OED differs from the file name (case counts) | fix the meter's Name, or the `meterName` field |
| Upload: `... is an unexpected argument` | a typo in a field name, or a field of another OED version (`meterIdentifier`, `username` are not in v1.0.0) | use exactly the fields of C.4 |
| Upload: `TypeError`, `invalid message format` | `gzip` wrong | add `-F 'gzip=no'` for our plain files |
| Upload: `No csv file was uploaded` | `csvfile` field missing or the path is wrong | check the `@/srv/...` path with `ls` |
| Energy, first upload: "The first ever reading must be dropped" and HTTP 500 | normal for a cumulative meter | nothing to do |
| Energy: "A negative meterReading has been detected ... Reject all readings" | the counter went down (meter reset, bad read, meter changed) | nothing was stored; look at the day file and alarm A19; do not switch on Cumulative Reset without understanding why |
| Energy: "The end of the previous reading is too far from the start of the next readings" | a gap longer than the meter's Reading Gap | the reading is dropped; check Reading Gap is 3600 (B.5) |
| Energy: "The reading start time is before the previous end time and the data is cumulative" | the day, or part of it, was already uploaded | nothing to do for the old part; never upload a day twice |
| Sensor file rejected because of duplicate readings | the day was already uploaded | skip it, or use `update=yes` on purpose (C.8) |
| Graph shows nothing after an upload | views not refreshed, browser not reloaded, meter not displayable, no unit chosen, or time range zoomed elsewhere | C.6 step 1; reload; check the meter's Displayable and Unit; **Restore** on the line graph |
| Day curve shifted by 8 hours | file with UTC times uploaded, or a computer clock in another zone (compare graph) | the export must start at 08:00 for a UTC day (C.3 step 4); check your computer's time zone |
| "Cannot create bar graph on raw units such as temperature" | bar and compare do not work for raw units | use the line graph (D.5) |
| `429 Too Many Requests` | OED allows 200 requests per 5 s per address, and behind Caddy everyone shares one address (`src/server/app.js`) | wait a few seconds; tell the owner if it happens often |
| Web restarts by itself, `OOMKilled true` | memory limit hit | E.6 |
| `caddy validate` fails | syntax error in the site file | put back `/opt/edge/monitoring.caddy.before-oed`, report the error |

---

## Appendix A: command cheat sheet

Run on the VPS as `ai` unless marked. "OED folder" = `/opt/arkan-monitoring/server/deploy/oed`.

| Task | Command |
|---|---|
| State of OED | `docker compose ps` (OED folder) |
| OED web log | `docker compose logs web --tail 50` (OED folder) |
| Database log | `docker compose logs database --tail 50` (OED folder) |
| Start everything | `docker compose up -d` (OED folder) |
| Restart OED web | `docker compose restart web` (OED folder) |
| OED version | `curl -s http://127.0.0.1:8810/api/version` |
| Memory | `docker stats --no-stream arkan-oed-web arkan-oed-db arkan-monitoring-ingest` |
| New OED admin user | `docker compose exec web npm run createUser` (OED folder) |
| Change an OED user's password | `docker compose exec web npm run editUser` (OED folder) |
| Export one UTC day | `docker exec arkan-monitoring-ingest python tools/manage.py export-oed adab --from <day> --to <day>` |
| Upload energy | C.4 step 1 |
| Upload sensors | C.4 step 2 |
| Refresh all views | `docker exec arkan-oed-web npm run --silent refreshAllReadingViews` |
| Backup now | `/opt/arkan-monitoring/server/deploy/oed/oed-backup.sh` |
| Caddy check (owner) | `sudo caddy validate --config /etc/caddy/Caddyfile` |
| Caddy reload (owner, approved) | `sudo systemctl reload caddy` |
| Build image (laptop) | `docker build -t arkan-oed:v1.0.0 --build-arg OED_REF=v1.0.0 server/deploy/oed` |

## Appendix B: glossary

| Term | Meaning |
|---|---|
| Admin (OED) | OED user with every right: meters, units, groups, users, settings |
| basicauth | The login box the browser shows, asked by Caddy, using the shared Arkan logins file |
| Caddy | The web server in front of everything on the VPS: HTTPS, logins, sends each path to the right program |
| Container | A program running in Docker with its own files, limited in memory |
| Conversion | OED's link between two units: destination = slope x source + intercept |
| CSV | Text file with values separated by commas, one line per record |
| CSV role | OED user who may only upload CSV files |
| Cumulative | A counter that only grows (like a car's odometer); usage = this value minus the previous one |
| curl | Command-line tool that sends web requests |
| Docker, Docker Compose | Docker runs containers; Compose starts several from one file (`docker-compose.yml`) |
| Group | OED set of meters (and groups) added together, here the site and all sites |
| Image | The frozen content of a container; ours is `arkan-oed:v1.0.0` |
| Loopback, 127.0.0.1 | Addresses reachable only from the VPS itself |
| Materialized view, view refresh | Stored summary tables (hourly, daily) OED uses for fast graphs; they must be recomputed after new data |
| Meter (OED) | One series of readings with one unit, for example `adab-EM01-energy` |
| Meter unit | The unit a meter collects in; never shown to people, converted to a graphing unit |
| Multi-stage build | A Dockerfile that builds in one image and copies only the result into a small one |
| Node.js | The JavaScript program OED's server runs on |
| PostgreSQL, pg_dump | OED's database; `pg_dump` writes a full copy of it as SQL |
| Raw (unit) | A unit that is averaged, not added: temperature, humidity, volts, amperes |
| Reading | One value with a start and an end time |
| Tag | A fixed name for one version of code (`v1.0.0`) |
| UTC, WITA | UTC is world time; WITA is Central Indonesia time, UTC + 8, no daylight saving, the hotel's time |

## Appendix C: version record and open points

**Version record** (fill in at install):

| Item | Value |
|---|---|
| OED tag | v1.0.0 |
| OED commit (`OED_COMMIT` in the image) | |
| Image size | |
| Installed on (date) | |
| RAM before OED (`free -h`, available) | |
| RAM after OED, idle (`docker stats`: web / db / ingest) | |
| RAM during a view refresh | |

**To verify the first time:**
1. The build works as written (`npm ci`, `npm run webpack:build`, `npm prune --production` with Node 16.13.2), and `node:16.13.2-slim` exists.
2. The VPS is `x86_64`.
3. The exact answer of `/api/version`.
4. The web log line after `createdb` on a new database.
5. That 320 MB is enough for OED web during a view refresh run with `docker exec` in the same container.
6. The `postgres` user id (999) in the database container.
7. Exact button labels in OED's admin pages (taken from `translations/data.js` and the help pages; screens may differ slightly).
8. That `curl -F 'password=<file'` sends the file content exactly (the file is written without a line end on purpose).
9. The restore procedure E.3, once on a laptop.
10. The compare graph takes "now" from the browser's clock and time zone.
11. Whether OED offers a way to remove or replace past cumulative readings (C.8).
12. The draft Caddy file, `docker-compose.yml` and PostgreSQL settings, on a test run (they were checked for syntax only: `docker compose config` passed; Caddy was not available to validate).

**Fixed in our files after review (7 November 2026):**
- The exporter now chains the energy readings: each one starts where the previous one ended (up to a 60 minute gap), so a missing minute no longer leaves a hole that OED drops. Reading Gap 3600 on the energy meter stays as a safety net for longer gaps.
- The exporter's closing message now says `headerRow=yes, gzip=no`.
