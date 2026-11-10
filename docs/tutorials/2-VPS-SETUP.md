# Tutorial 2: the VPS setup, step by step

This tutorial sets up the **ingest service** on the VPS `hermes-vps`: the program that receives the 1-minute records of the Adab logger (`LOG-0001`, site code `adab`), stores them in plain files, checks the alarms and serves the live page at `https://arkan-monitoring.duckdns.org/live/`.

It is written for a beginner. Every term is explained the first time, every command is given in full with the result you should see, and every step says on which machine it runs and who runs it.

| | |
|---|---|
| **For** | The operator (a team member, working as user `ai`), with the **owner** for the steps that need `sudo` and for every approval |
| **Where** | Your Windows laptop (PowerShell) and `hermes-vps` (over SSH) |
| **Time** | About half a day for part B, with the owner available |
| **Before** | Nothing. This tutorial comes first (see [README.md](README.md)) |
| **After** | [Tutorial 1](1-LOGGER-ON-SITE.md) (the logger) and [tutorial 3](3-OPEN-ENERGY-DASHBOARD.md) (Open Energy Dashboard) |
| **Short reference** | [../VPS-SETUP.md](../VPS-SETUP.md) is the short version of this tutorial. This tutorial follows its steps and explains them |

**Status (8 November 2026).** The ingest service, the alarm engine, the site page (live values, history pages, meter register page, remote firmware update), the remote settings, the OTA files and the admin tool `manage.py` exist and pass their tests ([../../server/tests/test_ingest.py](../../server/tests/test_ingest.py)). **WhatsApp alerts through Hermes are not built yet** (session S6). **Open Energy Dashboard (OED) is not installed yet** (tutorial 3).

## How to read this tutorial

Every command block says where it runs:

| Label | Meaning |
|---|---|
| **Laptop (PowerShell)** | On your Windows laptop, in a PowerShell window. Block marked `powershell` |
| **VPS, user ai** | On `hermes-vps`, after `ssh hermes-vps`, as user `ai`, without `sudo`. Block marked `bash` |
| **VPS, owner with sudo** | On `hermes-vps`, run **by the owner** (the only person allowed to use `sudo`). Block marked `bash` |

Rules for every block:
- **One command per block.** Copy the whole line, paste it, press Enter.
- **Do not type the prompt.** On the VPS the screen shows something like `ai@hermes-vps:~$` before the cursor; on the laptop `PS C:\Users\you>`. That is the prompt, not part of the command.
- **Placeholders** are written `<like-this>`. Replace the whole thing, brackets included, with the real value. Never paste a placeholder as it is (in PowerShell, `<` has a special meaning and the command fails).
- **To verify** marks something this tutorial could not check from the repository. The text says how to check it. Write down the answer for the next person.

| Placeholder | What to put |
|---|---|
| `<VPS_PUBLIC_IP>` | The public IP address of hermes-vps (ask the owner) |
| `<VPS_USER>` | The Linux user you log in as: normally `ai` (ask the owner) |
| `<your-name>` | Your name, to label your SSH key |
| `<tag>` | The git tag to install, for example `v0.4.0` (ask the owner) |
| `<previous-tag>` | The tag that was running before an update |
| `<stamp>` | The time part of a backup file name, for example `20261108T0230Z` |
| `<date>` | Today's date, for example `2026-11-07` |
| `<hub-user>` | Your login for the Arkan dashboards (from the owner) |

Real secrets (tokens, passwords, IP addresses) never go into this file, a chat, an email or a screenshot.

## Contents

- [Part 0. The ideas and the map](#part-0-the-ideas-and-the-map)
- [Part A. The laptop](#part-a-the-laptop)
- [Part B. First installation](#part-b-first-installation)
- [Part C. Everyday operations](#part-c-everyday-operations)
- [Part D. Troubleshooting](#part-d-troubleshooting)
- [Part E. Security checklist](#part-e-security-checklist)
- [Appendix 1. Command cheat sheet](#appendix-1-command-cheat-sheet)
- [Appendix 2. File and folder cheat sheet](#appendix-2-file-and-folder-cheat-sheet)
- [Appendix 3. Glossary](#appendix-3-glossary)

---

## Part 0. The ideas and the map

### 0.1 The words you need

**VPS (Virtual Private Server).** A computer rented in a data centre, here from Hostinger. It runs Ubuntu Linux, is always on and has a public IP address. Ours is called `hermes-vps`. It already runs other Arkan services (the Arkan Hub, the CMMS, Hermes the WhatsApp agent). We add one more service beside them and leave them alone.

**SSH (Secure Shell).** The way to type commands on the VPS from your laptop. You type `ssh hermes-vps` in PowerShell; from then on, what you type runs on the VPS, until you type `exit`. The connection is encrypted. **scp** (secure copy) uses the same connection to copy files between the laptop and the VPS.

**SSH key.** A pair of files made on your laptop. The **private key** (`id_ed25519`) stays on your laptop and is never shared. The **public key** (`id_ed25519.pub`) is given to the owner, who adds it to the VPS. The VPS then lets you in without a password, because only your laptop holds the matching private key.

**Linux user, sudo.** On the VPS every person or program works as a **user**. We work as user `ai`. A user can only change its own files. **`sudo`** ("do as the administrator") runs one command with full rights over the whole machine. House rule ([../PLAN.md](../PLAN.md) section 4.3): **sessions and operators do not use `sudo`; only the owner does.** Every `sudo` step in this tutorial is marked "owner with sudo".

**Docker, image, container.** Docker runs programs in **containers**: a container is a closed box with its own files, its own Python, and limits on memory and CPU, so it cannot disturb the other services. A container is started from an **image**: the frozen recipe (Python 3.12, our code, the alarm register). The image is built from the **Dockerfile** ([../../server/Dockerfile](../../server/Dockerfile)). Our container is called `arkan-monitoring-ingest`, our image `arkan-monitoring-ingest:local`.

**docker compose.** A tool that reads a file, [../../server/docker-compose.yml](../../server/docker-compose.yml), describing how to build and run the container (its port, its data folder, its 96 MB memory limit, its restart rule). You always run it **in the folder that holds that file**: `/opt/arkan-monitoring/server`. In compose, our container is the **service** named `ingest`.

**Reverse proxy (Caddy).** The internet does not talk to our container directly. **Caddy**, a web server already installed on hermes-vps (version 2.6, installed natively, not in Docker), receives every web request on the standard ports 80 and 443, checks it, and passes it on ("proxies" it) to the right service inside the VPS. Each service has a small **site file** in `/opt/edge/sites/`. Ours is `monitoring.caddy`. Caddy also asks for the **Arkan login** (the same usernames and passwords as the other dashboards, kept in `/opt/edge/secrets/hub-users.caddy`).

**HTTPS certificate.** HTTPS is encrypted HTTP. To use it, the server needs a **certificate** that proves it owns the name `arkan-monitoring.duckdns.org`. Caddy gets one automatically and free from Let's Encrypt the first time the site is loaded, and renews it by itself. For this, the name must point to the VPS and ports 80 and 443 must be reachable from the internet.

**DuckDNS.** A free service that gives names ending in `.duckdns.org` and points them to an IP address. The owner creates the name `arkan-monitoring`, so `arkan-monitoring.duckdns.org` leads to hermes-vps.

**Port, loopback.** A **port** is a numbered door on a computer: 443 for HTTPS, 22 for SSH. Each service listens on its own port. The **loopback** address `127.0.0.1` means "this same machine": a port opened on `127.0.0.1` can only be reached **from inside the VPS**, never from the internet. Our container listens on **`127.0.0.1:8800`**. Only Caddy, on the same VPS, can reach it. Other ports in use: the Hub 8780, the CMMS 8790, the Hermes webhook 8644.

**Token.** A long random password that belongs to one logger. The logger sends it with every request (`Authorization: Bearer <token>`). The service keeps only a **hash** of it (SHA-256, a one-way fingerprint), never the token itself, so it is shown **once**, when the logger is added. A lost token cannot be recovered: you make a new one.

**Git tag.** A fixed name for one version of the code, for example `v0.4.0`. House rule: **the VPS only runs tagged versions**, never "the latest work in progress". Updating = checking out a newer tag.

**cron.** The Linux scheduler. A line in a **crontab** (a user's list of scheduled jobs) runs a command at fixed times, for example the backup every night at 02:30.

### 0.2 How it fits together

```
 ADAB HOTEL                                     hermes-vps (Hostinger, Ubuntu)
 +--------------------+                         +--------------------------------------------------+
 | Logger LOG-0001    |                         |  Caddy 2.6 (native), ports 80 and 443            |
 | ESP32-S3 + SD card |  HTTPS, hotel WiFi      |  site file /opt/edge/sites/monitoring.caddy      |
 | 1-min records  ----+---> INTERNET ---------->|   logger paths: no login, token checked later    |
 | live every 15 s    |                         |   people paths: Arkan login (hub-users.caddy)    |
 +--------------------+          ^              |        |                                         |
                                 |              |        | 127.0.0.1:8800 (loopback only)          |
 PHONE OR PC (browser) ----------+              |        v                                         |
   https://arkan-monitoring.duckdns.org/live/   |  Docker container arkan-monitoring-ingest        |
                                                |   server.py: ingest, live page, alarms           |
                                                |   96 MB, read-only except /data                  |
                                                |        |                                         |
                                                |        v  mounted at /data in the container      |
                                                |  /srv/arkan-monitoring/data/   (the record)      |
                                                |  /srv/arkan-monitoring/backups/ (nightly)        |
 YOUR LAPTOP (Windows, PowerShell)              |                                                  |
   ssh hermes-vps, scp ---- SSH, port 22 ------>|  user ai: docker compose, manage.py, crontab     |
                                                |                                                  |
                                                |  Left alone: Hub (8780), CMMS (8790),            |
                                                |  Hermes (webhook 8644, never public)             |
                                                |  Later: Open Energy Dashboard behind "/"         |
                                                +--------------------------------------------------+
```

What happens when the logger sends a record:
1. Every minute the logger writes the record on its SD card, then posts the new lines of its day file to `https://arkan-monitoring.duckdns.org/api/v1/ingest` with its token.
2. Caddy sees an `/api/v1/ingest` path, does not ask for a login (a logger cannot type one), limits the size, and passes the request to `127.0.0.1:8800`.
3. The service checks the token, checks every row, appends the new rows to the day file in `/srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/`, runs the alarm checks, writes any alarm line to `sites/adab/alarms/2026.csv`, and answers `{"ok": true, "stored": ...}`.
4. If the answer does not come (no WiFi, VPS down), the logger keeps the rows on its SD card and sends them later. Nothing is lost.
5. Every 15 s the logger also posts a small "live" snapshot. It is shown on the live page and saved in the data folder for 7 days (`live.json`, `live/<day>.jsonl`), so another dashboard can read it too.

Where the next parts will plug in:
- **Open Energy Dashboard** (tutorial 3) will run in its own containers on another loopback port; Caddy's `/` will then go to OED instead of the live page. Until then `/` redirects to `/live/`. The files for OED are made by `manage.py export-oed` (section C12).
- **WhatsApp alerts** (session S6) will be sent through Hermes. The alarm register already has the `whatsapp` column; nothing is sent today.

### 0.3 Where everything lives on the VPS

| Path | What is in it | Who changes it |
|---|---|---|
| `/opt/arkan-monitoring/` | The code: a copy (git clone) of this repository, checked out at a tag | Owner clones it once; operator checks out tags |
| `/opt/arkan-monitoring/server/` | `docker-compose.yml`, `Dockerfile`: **run every `docker compose` command here** | Nobody edits by hand |
| `/opt/arkan-monitoring/server/.env` | Optional: another port or data folder (only if 8800 is taken) | Operator, only if needed |
| `/srv/arkan-monitoring/data/` | **The data folder: the record.** Owned by uid 1000, mode 750. Seen as `/data` inside the container | The service and `manage.py`; people only read, except the files named below |
| `/srv/arkan-monitoring/data/devices.json` | Loggers: site, token **hash**, firmware version | `manage.py` only |
| `/srv/arkan-monitoring/data/alarm-register.csv` | **The alarm register in use** (opened in Excel) | Operator (section C6) |
| `/srv/arkan-monitoring/data/sites/adab/site.json` | Site profile: name, timezone, labels, live values, 82.5 kVA, 200 A | Operator, by hand, rarely |
| `/srv/arkan-monitoring/data/sites/adab/alarm-register.csv` | Optional per-site lines of the register | Operator (section C6) |
| `/srv/arkan-monitoring/data/sites/adab/alarms/2026.csv` | **The alarm log** of the site, one file per year | The service only |
| `/srv/arkan-monitoring/data/sites/adab/daily.csv` | One row per WITA day | `manage.py daily` |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/2026/11/2026-11-07.csv` | **The 1-minute records**, one file per UTC day, same as on the SD card | The service only. **Never delete** |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/events.jsonl` | Boots, firmware changes, settings, backfills | The service and `manage.py` |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/config.json` | Settings asked for the logger (`set-config`) | `manage.py set-config` |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/settings-reported.json` | Settings the logger reported after its last boot (and the register table it reads) | The service |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/registers.json`, `registers-history.jsonl` | Meter register table last sent from the page `/live/adab/register`, and every version sent | The register page, `manage.py set-registers` |
| `/srv/arkan-monitoring/data/sites/adab/LOG-0001/alarm-state.json` | Open alarms and pending delays (internal) | The service |
| `/srv/arkan-monitoring/data/firmware/` | `manifest.json` and `logger-x.y.z.bin` for OTA updates | **Firmware update** on the site page, `manage.py publish-fw` |
| `/srv/arkan-monitoring/data/export/` | Working folder: OED files, SD card copies, temporary files | Operator; keep it tidy |
| `/srv/arkan-monitoring/data/logs/` | Created by the setup script, not used yet (the service log is in Docker, section C1) | |
| `/srv/arkan-monitoring/backups/` | `data-<stamp>.tar.gz` (14 kept) and `backup.log` | `backup.sh` from cron |
| `/opt/edge/sites/monitoring.caddy` | Our Caddy site file (copied from the repository) | Owner |
| `/opt/edge/secrets/hub-users.caddy` | The shared Arkan logins (password hashes) | Owner only. Never copy it |
| `/opt/edge/secrets/monitoring-users.caddy` | The logins for this platform only, for example a technician (password hashes; [../LIVE.md](../LIVE.md#logins)) | Owner only. Never copy it |
| `/etc/caddy/Caddyfile` | Caddy's main file, which imports the site files (**to verify**, section B8) | Owner only |
| `/var/log/caddy/arkan-monitoring.log` | Caddy's access log for our site (tokens and cookies removed) | Caddy |
| Docker image `arkan-monitoring-ingest:local` | Built on the VPS from the Dockerfile | `docker compose up -d --build` |
| Docker container `arkan-monitoring-ingest` | The running service; its log is kept by Docker (3 files of 10 MB at most) | `docker compose` (owner approves restarts) |

### 0.4 Where everything is in the repository

| File | What it is |
|---|---|
| [../../server/app/server.py](../../server/app/server.py) | The web service: device endpoints, site page, status, alarms, history and admin API |
| [../../server/app/store.py](../../server/app/store.py) | The data folder: checks and stores the rows, tokens, settings |
| [../../server/app/alarms.py](../../server/app/alarms.py) | The alarm engine |
| [../../server/app/live.html](../../server/app/live.html) | The site page `/live/<site>/`: live now, history pages, meter registers, firmware update, settings (and the overview `/live/`). Its look comes from the Arkan UI kit in [../../server/app/arkan-ui/](../../server/app/arkan-ui/), served at `/live/_ui/` |
| [../../server/app/history.py](../../server/app/history.py) | Hourly and 1-minute summaries of the day files for the history pages |
| [../../server/app/registers.py](../../server/app/registers.py) | The checks of the meter register page (`/live/<site>/#register`, in `live.html`) |
| [../../server/app/firmware.py](../../server/app/firmware.py) | Firmware checks, offers per logger, GitHub releases ([../OTA.md](../OTA.md)) |
| [../../server/tools/manage.py](../../server/tools/manage.py) | The admin tool (every command in Part C) |
| [../../server/tools/simulate_logger.py](../../server/tools/simulate_logger.py) | A fake logger, to test without the board |
| [../../server/tests/test_ingest.py](../../server/tests/test_ingest.py) | The automatic tests |
| [../../server/Dockerfile](../../server/Dockerfile) | How the image is built |
| [../../server/docker-compose.yml](../../server/docker-compose.yml) | How the container runs (port, data folder, limits) |
| [../../server/.env.example](../../server/.env.example) | Example of `.env`: port, and who may update firmware from the web page |
| [../../.dockerignore](../../.dockerignore) | What goes into the image (only the app, the tools and the alarm register) |
| [../../server/deploy/setup-vps.sh](../../server/deploy/setup-vps.sh) | One-time preparation of the data folder (owner) |
| [../../server/deploy/backup.sh](../../server/deploy/backup.sh) | Nightly backup |
| [../../server/deploy/monitoring.caddy](../../server/deploy/monitoring.caddy) | The Caddy site file |
| [../alarms/alarms.csv](../alarms/alarms.csv) | The default alarm register (built into the image) |
| [../alarms/README.md](../alarms/README.md), [../DATA-FORMAT.md](../DATA-FORMAT.md), [../LIVE.md](../LIVE.md), [../VPS-MEMORY.md](../VPS-MEMORY.md) | Reference documents |

### 0.5 Who does what

| Task | Owner (with sudo) | Operator (user ai, no sudo) |
|---|---|---|
| Add your SSH public key to the VPS | Does it | Sends the `.pub` file |
| Checks before installing (part B, B1 to B9) | | Does them, reports to the owner |
| Swap file, firewall, DuckDNS name | Does them | Checks the result |
| `git clone` into `/opt/arkan-monitoring`, `setup-vps.sh` | Does them | Reads the dry run with the owner |
| Checking out a tag | Approves which tag | Does it |
| First start, every restart, stop or rebuild of the container | **Approves each one** | Types the command once approved |
| `manage.py init`, `add-site`, `list`, `alarms`, `daily`, `export-oed`, `backfill`, `set-config`, `show-config` | | Does them |
| `add-device`, `rotate-token` (they print secrets) | Runs them, or is present ([../QUESTIONS.md](../QUESTIONS.md) Q17) | |
| Copying the Caddy file, `caddy validate`, Caddy reload | Does them, **approves the reload** | Prepares, checks with curl |
| Crontab lines (backup, daily summary) | Approves them | Adds them if the owner says so |
| Real restore of a backup | Does it | Test restore into a test folder |

---

## Part A. The laptop

### A1. Check that the SSH client is installed

**Where:** Laptop (PowerShell). Open PowerShell: Start menu, type `PowerShell`, click **Windows PowerShell**.

```powershell
ssh -V
```

**Expected:** a line such as `OpenSSH_for_Windows_9.5p1, LibreSSL 3.8.2` (the numbers vary).

**If different:** `ssh : The term 'ssh' is not recognized` means the OpenSSH client is missing. It is a Windows optional feature: Settings, then System (Windows 11) or Apps (Windows 10), then Optional features, then add **OpenSSH Client**. If you are not allowed to install features, ask IT. An administrator PowerShell can also add it:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

### A2. Make your SSH key

**Where:** Laptop (PowerShell). Do this once per laptop.

```powershell
ssh-keygen -t ed25519 -C "<your-name>@arkan"
```

It asks three questions:
1. `Enter file in which to save the key`: press Enter (keeps the default `C:\Users\<you>\.ssh\id_ed25519`).
2. `Enter passphrase`: type a passphrase you will remember (it protects the key if the laptop is stolen), then Enter.
3. `Enter same passphrase again`: type it again.

**Expected:** `Your identification has been saved in C:\Users\<you>/.ssh/id_ed25519` and `Your public key has been saved in C:\Users\<you>/.ssh/id_ed25519.pub`, then a small picture of random characters.

**If different:** `id_ed25519 already exists. Overwrite (y/n)?` means you already have a key. Answer **n** and use the existing one.

### A3. Give your public key to the owner

**Where:** Laptop (PowerShell).

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
```

**Expected:** one line starting with `ssh-ed25519 AAAA` and ending with `<your-name>@arkan`.

Send **this line only** (the `.pub` file) to the owner. Never send the file without `.pub`: that is your private key.

The owner adds it as a new last line of `/home/ai/.ssh/authorized_keys` on the VPS, without removing the other lines, and gives you two things: the VPS IP address and the **host key fingerprint** of the VPS (a line starting with `SHA256:`). The owner gets the fingerprint with this command (**VPS, owner**, no sudo needed):

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

**Expected:** `256 SHA256:... root@... (ED25519)`.

### A4. Write the `hermes-vps` entry in your SSH config

The SSH config file lets you type `ssh hermes-vps` instead of the full address. It is `C:\Users\<you>\.ssh\config` (no extension).

**Where:** Laptop (PowerShell). First create the file if it does not exist (this command refuses to touch an existing file):

```powershell
New-Item -ItemType File -Path $env:USERPROFILE\.ssh\config
```

**Expected:** a short table with `Name: config`. **If** it says `The file ... already exists`: fine, keep it, and add the entry below at the end.

Open it in Notepad:

```powershell
notepad $env:USERPROFILE\.ssh\config
```

Add these lines at the end (replace the two placeholders), then File, Save:

```text
Host hermes-vps
    HostName <VPS_PUBLIC_IP>
    User <VPS_USER>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ServerAliveInterval 30
```

Check that Notepad did not add `.txt`:

```powershell
Get-ChildItem $env:USERPROFILE\.ssh
```

**Expected:** `config`, `id_ed25519`, `id_ed25519.pub` (and maybe `known_hosts`). **If** you see `config.txt` instead of `config`, rename it:

```powershell
Rename-Item $env:USERPROFILE\.ssh\config.txt config
```

### A5. First login

**Where:** Laptop (PowerShell).

```powershell
ssh hermes-vps
```

The first time, SSH shows the VPS fingerprint:

```text
The authenticity of host '<VPS_PUBLIC_IP>' can't be established.
ED25519 key fingerprint is SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Compare the `SHA256:` part, character by character, with the one the owner gave you. Same: type `yes` and Enter. **Different: type `no` and call the owner** (you might not be talking to our VPS).

Then type your key passphrase.

**Expected:** a welcome text from Ubuntu, then a prompt like `ai@<hostname>:~$`. You are now on the VPS.

**If different:**
- `Permission denied (publickey)`: the owner has not added your key yet, or added it to another user. Check `User` in your config.
- `Connection timed out`: wrong IP in `HostName`, or your network blocks port 22. Try from another network.

To leave the VPS and come back to the laptop:

```bash
exit
```

### A6. The Linux commands you need

**Where:** VPS, user ai. Try each one after `ssh hermes-vps`.

| Command | What it does | Example |
|---|---|---|
| `pwd` | Shows the folder you are in | `pwd` |
| `cd <folder>` | Goes into a folder. `cd` alone goes home (`/home/ai`), `cd ..` goes up one level | `cd /opt/arkan-monitoring/server` |
| `ls` | Lists a folder. `ls -l` adds sizes, owners, dates. `ls -la` also shows hidden files | `ls -l /srv/arkan-monitoring/data` |
| `cat <file>` | Prints a whole (small) file | `cat /srv/arkan-monitoring/data/sites/adab/site.json` |
| `less <file>` | Reads a long file page by page. Space = next page, `/word` = search, `q` = quit | `less /srv/arkan-monitoring/data/sites/adab/alarms/2026.csv` |
| `head -n 5 <file>`, `tail -n 5 <file>` | First or last 5 lines | `tail -n 5 /srv/arkan-monitoring/backups/backup.log` |
| `tail -f <file>` | Follows a file as it grows. **Ctrl+C** to stop | `tail -f /srv/arkan-monitoring/data/sites/adab/alarms/2026.csv` |
| `nano <file>` | A simple text editor. **Ctrl+O** then Enter = save, **Ctrl+X** = quit | `nano /srv/arkan-monitoring/data/sites/adab/site.json` |
| `df -h` | Free disk space, in readable units | `df -h /srv` |
| `free -h` | Free memory (RAM) and swap | `free -h` |
| `du -sh <folder>` | Size of a folder | `du -sh /srv/arkan-monitoring/data` |
| `wc -l <file>` | Counts the lines of a file | `wc -l /srv/arkan-monitoring/data/devices.json` |
| `grep <word> <file>` | Shows the lines that contain a word | `grep A05 /srv/arkan-monitoring/data/sites/adab/alarms/2026.csv` |
| **Ctrl+C** | Stops the command that is running | |
| **Up arrow** | Brings back the previous command | |

Two safety rules on the VPS:
- **Never use `rm` (delete) on a path you have not checked with `ls` first.** Linux has no recycle bin.
- **Never overwrite an existing file** (house rule). Before writing or uploading a file, check with `ls -l <path>` that nothing is there, or use a new name.

### A7. Copying files with scp

`scp` runs **on the laptop** and copies between the laptop and the VPS. The VPS side is written `hermes-vps:<path on the VPS>`.

Make a working folder on the laptop once:

**Where:** Laptop (PowerShell).

```powershell
New-Item -ItemType Directory -Path $env:USERPROFILE\arkan
```

```powershell
Set-Location $env:USERPROFILE\arkan
```

From the VPS to the laptop (download), for example the site profile:

```powershell
scp hermes-vps:/srv/arkan-monitoring/data/sites/adab/site.json .
```

**Expected:** `site.json   100%  1234   10.0KB/s   00:00`. The `.` means "here", the current laptop folder.

A whole folder needs `-r` (recursive):

```powershell
scp -r hermes-vps:/srv/arkan-monitoring/data/sites/adab .\adab-<date>
```

From the laptop to the VPS (upload):

```powershell
scp .\somefile.csv hermes-vps:/srv/arkan-monitoring/data/export/somefile.csv
```

**Warning:** `scp` overwrites the target without asking. Always upload to a **new** name and check first with `ls -l` on the VPS.

### A8. Python and curl on the laptop

You need Python 3 on the laptop for the simulated logger (part B25). It uses only the standard library: nothing to install with pip.

**Where:** Laptop (PowerShell).

```powershell
python --version
```

**Expected:** `Python 3.10.x` or newer. **If** it says `Python was not found` or opens the Microsoft Store: install Python 3 from python.org (tick **Add python.exe to PATH**), or ask IT (**to verify**: the company's rule for installing software).

For the web checks, use **`curl.exe`**, not `curl`. In Windows PowerShell, `curl` alone is another command (`Invoke-WebRequest`) with different options. `curl.exe` is included in Windows 10 and 11:

```powershell
curl.exe --version
```

**Expected:** `curl 8.x.x (Windows) ...`.

---

## Part B. First installation

Do the steps in order. Write down every result that differs from "Expected" and show it to the owner before going on.

### B1. Who you are on the VPS

**Where:** VPS, user ai.

```bash
id
```

**Expected:** `uid=1000(ai) gid=1000(ai) groups=1000(ai),...,<number>(docker)`.

Two things matter:
- **`docker` in the groups**: you can run Docker without `sudo`. **If missing**, the owner decides whether to add you (membership of the `docker` group is as powerful as `sudo`). **VPS, owner with sudo**, then you log out (`exit`) and in again:

```bash
sudo usermod -aG docker ai
```

- **`uid=1000`**: the data folder belongs to uid 1000 (the user the container runs as). If `ai` is uid 1000, you can read the data files directly and copy them with `scp`. **To verify.** If `ai` has another uid, tell the owner: you will not be able to read `/srv/arkan-monitoring/data` directly, and every "read a file" command in this tutorial must go through the container instead, for example `docker compose exec ingest cat /data/sites/adab/alarms/2026.csv` (run in `/opt/arkan-monitoring/server`).

### B2. What already runs on the VPS

**Where:** VPS, user ai.

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

**Expected:** a table of the containers that already run (the Hub, the CMMS and others), with `Up ...` in the status column. Note their names. **Do not stop, restart or remove any of them.** There must be no container called `arkan-monitoring-ingest` yet.

```bash
ss -ltn
```

**Expected:** the list of ports in use (`State LISTEN`). You should see `:22` (SSH), `:80` and `:443` (Caddy), `127.0.0.1:8780` and `127.0.0.1:8790` (Hub and CMMS), and others. Keep this list: you will compare after the install.

### B3. Docker and compose

**Where:** VPS, user ai.

```bash
docker --version
```

**Expected:** `Docker version 2x.x.x, build ...`.

```bash
docker compose version
```

**Expected:** `Docker Compose version v2.x.x`.

**If different:** Docker is already on hermes-vps (the Hub and the CMMS use it): **do not reinstall it.** If `docker compose` (with a space) is unknown, tell the owner: the compose plugin is needed. Installing Docker is only for a new, empty VPS ([../VPS-SETUP.md](../VPS-SETUP.md) section 2).

### B4. Memory and swap

**Where:** VPS, user ai.

```bash
free -h
```

**Expected:** two lines, `Mem:` and `Swap:`. Look at the `available` column of `Mem:`. Our service needs at most 96 MB; OED later will need about 300 to 450 MB more for the whole platform ([../VPS-MEMORY.md](../VPS-MEMORY.md)). Write down the figure.

```bash
swapon --show
```

**Expected:** a line such as `/swapfile file 2G ...`. **If it prints nothing**, there is no swap. Swap is disk space used as emergency memory: a safety net, not working memory. The owner adds a 2 GB swap file ([../VPS-MEMORY.md](../VPS-MEMORY.md)):

**VPS, owner with sudo**, only if `swapon --show` printed nothing. First check that no `/swapfile` exists (expected: `No such file or directory`):

```bash
ls -l /swapfile
```

```bash
sudo fallocate -l 2G /swapfile
```

```bash
sudo chmod 600 /swapfile
```

```bash
sudo mkswap /swapfile
```

```bash
sudo swapon /swapfile
```

```bash
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

```bash
sudo sysctl vm.swappiness=10
```

**Expected:** `swapon --show` now shows `/swapfile`. The `fstab` line makes the swap come back after a reboot. To keep `vm.swappiness=10` after a reboot, the owner adds it to a **new** file in `/etc/sysctl.d/` (never edit an existing one without checking).

### B5. Disk space

**Where:** VPS, user ai.

```bash
df -h /
```

**Expected:** the `Avail` column shows several GB free. Our needs: about 0.7 MB a day per logger (about 260 MB a year), the backups (gzip divides by about 5, 14 kept), and the Docker image. Check the image size later with `docker images arkan-monitoring-ingest`.

**If** `Use%` is above 85 %, tell the owner before going on.

### B6. Port 8800 is free

**Where:** VPS, user ai.

```bash
ss -ltn | grep -E ':(8800|8780|8790)\b'
```

**Expected:** lines for `8780` and `8790` (Hub and CMMS), and **no line with `8800`**.

**If** 8800 is in use: we use another port, chosen with the owner. See step B14.

### B7. Clock and timezone of the VPS

**Where:** VPS, user ai.

```bash
timedatectl
```

**Expected:** `System clock synchronized: yes` and `Time zone: Etc/UTC (UTC, +0000)`.

Why it matters: the alarm "clock wrong" (A18) compares the logger's clock with the VPS clock, and the crontab times in Part C assume the VPS runs in UTC. Adab is in WITA (UTC+8, `Asia/Makassar`). **If** the time zone is not UTC, write it down: the cron times in C3 and C4 must be shifted.

### B8. How Caddy is set up (to verify)

The repository says Caddy 2.6 runs natively and reads the site files in `/opt/edge/sites/`. The exact service name and main file path are **to verify** here.

**Where:** VPS, user ai.

```bash
caddy version
```

**Expected:** `v2.6.x ...`.

```bash
systemctl status caddy --no-pager
```

**Expected:** `Active: active (running)`. This shows Caddy runs as a systemd service called `caddy`. **If** the unit is not found, ask the owner how Caddy is started: the reload command in B22 depends on it.

```bash
systemctl cat caddy --no-pager
```

**Expected:** a line `ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile` or similar. **The path after `--config` is the main Caddyfile.** This tutorial uses `/etc/caddy/Caddyfile`; replace it if yours differs.

```bash
grep -n import /etc/caddy/Caddyfile
```

**Expected:** a line importing the site files, such as `import /opt/edge/sites/*.caddy`. **If** you get `Permission denied`, the owner runs the same command with `sudo`. **If** there is no such line, stop: the owner decides how our site file will be loaded.

```bash
ls -l /opt/edge/sites/
```

**Expected:** the existing site files (for example the Hub's and the CMMS's) and **no `monitoring.caddy`** yet.

### B9. Nothing of ours exists yet

**Where:** VPS, user ai.

```bash
ls -ld /opt/arkan-monitoring /srv/arkan-monitoring
```

**Expected:** two lines `ls: cannot access ...: No such file or directory`.

**If** one of them exists: stop and ask the owner. Someone already started an install; never overwrite it.

### B10. The DuckDNS name (owner)

**Where:** the owner's browser, then the laptop.

1. The owner signs in at https://www.duckdns.org with the account that holds the other Arkan names.
2. In the sub domain field, the owner types `arkan-monitoring` and clicks **add domain**.
3. In the new line, the owner puts the VPS public IP in the current ip field and clicks **update ip**. (Button and field names: **to verify** on the page, they may change. DuckDNS free accounts are limited to a few names: **to verify** that one is still free.)
4. The owner adds `arkan-monitoring` to the DuckDNS update job that keeps the other names current (same DuckDNS token). **To verify**: where that job is on hermes-vps. The update address usually lists the names separated by commas, for example `domains=name1,name2,arkan-monitoring`. Ways to find the job (VPS; the first as ai, the others by the owner):

```bash
crontab -l
```

```bash
sudo crontab -l
```

```bash
systemctl list-timers --all
```

```bash
sudo grep -ril duckdns /etc/cron.d /etc/crontab /opt/edge
```

**Check from the laptop.** Where: Laptop (PowerShell).

```powershell
nslookup arkan-monitoring.duckdns.org
```

**Expected:** under `Non-authoritative answer:`, `Name: arkan-monitoring.duckdns.org` and `Address: <VPS_PUBLIC_IP>` (the same IP as in your SSH config).

**Check from the VPS.** Where: VPS, user ai.

```bash
dig +short arkan-monitoring.duckdns.org
```

**Expected:** the VPS public IP alone on one line. **If** `dig: command not found`, use:

```bash
getent hosts arkan-monitoring.duckdns.org
```

**If different:** a new name can take a few minutes to answer. If it still gives no address or another IP after 10 minutes, the owner checks the DuckDNS page. Do not go to B22 (Caddy) before this check passes: Caddy cannot get the certificate otherwise.

### B11. Get the code

**Where:** VPS, owner with sudo. The owner clones the repository into `/opt/arkan-monitoring`:

```bash
sudo git clone https://github.com/julien355/esp32-datalogging.git /opt/arkan-monitoring
```

**Expected:** `Cloning into '/opt/arkan-monitoring'...` then `done`. **If** git asks for a username and password, the repository is private: **to verify** with the owner how hermes-vps reads private repositories (for example a read-only deploy key, as for the other services). Do not type a personal password on the VPS.

```bash
sudo chown -R ai:ai /opt/arkan-monitoring
```

**Expected:** no output. The code now belongs to `ai`, so the operator can check out tags without `sudo`.

**Where:** VPS, user ai. Go into the code folder:

```bash
cd /opt/arkan-monitoring
```

List the tags:

```bash
git tag --list
```

**Expected:** a list of version names, for example `v0.4.0`. **If the list is empty**, no version has been tagged yet (the case on 8 November 2026; the first tag is planned as `v0.4.0`): the owner creates the tag on GitHub first (**to verify**: the tag name), then you fetch it with `git fetch --tags`.

Check out the tag the owner chose:

```bash
git checkout <tag>
```

**Expected:** `Note: switching to '<tag>'.`, a paragraph about `'detached HEAD' state`, and `HEAD is now at 1234abc ...`. "Detached HEAD" is normal here: it means "a fixed version, not a branch". Do not change files in `/opt/arkan-monitoring`.

```bash
git describe --tags
```

**Expected:** the tag name alone, for example `v0.4.0`. Write it down: it is the "current tag" for the next update.

### B12. The setup script, dry run (owner)

[setup-vps.sh](../../server/deploy/setup-vps.sh) prepares the dedicated data folder. Without `--apply` it only **shows** what it would do and changes nothing. Read the output with the owner.

**Where:** VPS, owner with sudo.

```bash
sudo bash /opt/arkan-monitoring/server/deploy/setup-vps.sh
```

**Expected** (sections in this order):
- `== Docker`: `docker: Docker version ...` and `compose: 2.x.x`;
- `== Memory (the service is limited to 96 MB)`: the `free -h` table;
- `== Port 8800 on the loopback`: `free`;
- `== Data folder /srv/arkan-monitoring/data`: lines `(would run) mkdir -p /srv/arkan-monitoring`, `.../data`, `.../data/sites`, `.../data/firmware`, `.../data/logs`, `.../data/export`, `.../backups`, then `(would create) /srv/arkan-monitoring/data/devices.json`, `(would run) chown -R 1000:1000 /srv/arkan-monitoring`, `(would run) chmod 750 ...`;
- `== Next steps`: a short list (the next steps of this tutorial are more complete; follow this tutorial);
- last line: `Nothing was changed. Run again with --apply.`

**If different:** `MISSING: install Docker first` or `MISSING: docker compose plugin`: back to B3. `PORT 8800 IS IN USE`: see B14. `exists: ...` lines mean a folder is already there: stop and check with the owner (B9).

### B13. The setup script, for real (owner)

**Where:** VPS, owner with sudo.

```bash
sudo bash /opt/arkan-monitoring/server/deploy/setup-vps.sh --apply
```

**Expected:** the same sections, with `+ mkdir -p ...`, `+ created /srv/arkan-monitoring/data/devices.json`, `+ chown -R 1000:1000 /srv/arkan-monitoring`, `+ chmod 750 ...` instead of "(would run)". The script never overwrites an existing file.

**Check.** Where: VPS, user ai.

```bash
ls -l /srv/arkan-monitoring/data
```

**Expected:** `devices.json`, `export`, `firmware`, `logs`, `sites`, all owned by `ai ai` (if ai is uid 1000) or by `1000 1000`.

### B14. The `.env` file: who may update firmware (and the port, if 8800 is taken)

`server/.env` (read by docker compose, never in git) holds the settings of this VPS. Start from the example; `cp -n` never overwrites an existing file.

**Where:** VPS, user ai.

```bash
cd /opt/arkan-monitoring/server
```

```bash
cp -n .env.example .env
```

```bash
chmod 600 .env
```

```bash
nano .env
```

- `ADMIN_USERS=`: the Arkan login names (from `hub-users.caddy`, ask the owner) allowed to send a firmware to a logger from the site page, comma separated, for example `ADMIN_USERS=julien`. Empty = **Firmware update** is off for everyone (the command line `manage.py publish-fw` still works). Everyone else with a login still sees the live values, the history and the register page.
- `USER_SITES=`: logins limited to some sites, `login:site` comma separated, for example `USER_SITES=tech-adab:adab` for a technician who must see only the Adab page ([../LIVE.md](../LIVE.md#logins)). Empty = every login sees every site.
- `FW_GITHUB_REPO=julien355/esp32-datalogging`: where the firmware releases are. Leave it.
- `FW_GITHUB_TOKEN=`: only if the repository is private ([../OTA.md](../OTA.md) section 6). Leave it empty otherwise.
- `INGEST_PORT=8800`: change it **only if B6 showed 8800 taken**, to the port agreed with the owner. The same port must then replace `8800` in the three `reverse_proxy 127.0.0.1:8800` lines of the Caddy site file (B22, done by the owner), and in the `curl` commands of this tutorial. The port inside the container stays 8800.

Save (Ctrl+O, Enter) and quit (Ctrl+X).

```bash
grep -E '^(ADMIN_USERS|USER_SITES|FW_GITHUB_REPO|INGEST_PORT)=' .env
```

**Expected:** the lines with your values (`USER_SITES` only if you set it). Never paste the token line into a chat or a screenshot.

### B15. Build and start the container (owner approves)

Starting a new container is a live change on hermes-vps: **ask the owner's OK first.**

**Where:** VPS, user ai.

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

What it does: `--build` builds the image from the Dockerfile (downloads `python:3.12-slim` the first time, adds our code), `up -d` starts the container in the background ("detached").

**Expected:** build steps scroll by (the first build takes one to a few minutes), then:

```text
 ✔ Container arkan-monitoring-ingest  Started
```

(The exact wording varies with the compose version.)

**If different:** an error during the build that mentions the network (`failed to resolve`, `TLS handshake timeout`) means the VPS cannot reach Docker Hub or the Debian mirrors: tell the owner. `port is already allocated`: back to B6 and B14. Anything else: Part D, "Container does not start".

### B16. Check the container

**Where:** VPS, user ai, in `/opt/arkan-monitoring/server`.

```bash
docker compose ps
```

**Expected:** one line, `arkan-monitoring-ingest`, image `arkan-monitoring-ingest:local`, status `Up ... (health: starting)` during the first minute, then `Up ... (healthy)`, ports `127.0.0.1:8800->8800/tcp`.

```bash
curl -s http://127.0.0.1:8800/health
```

**Expected:** `{"ok": true, "version": "0.4.0", "time": "2026-11-07T06:18:50Z"}` (your time; the version is the service version, not the tag).

```bash
ss -ltn | grep 8800
```

**Expected:** `LISTEN ... 127.0.0.1:8800 0.0.0.0:*`. **It must say `127.0.0.1:8800`**, never `0.0.0.0:8800` or `*:8800` (that would publish the service to the internet without the login).

```bash
docker compose logs --tail 20 ingest
```

**Expected:** a first line `... arkan-ingest 0.4.0 on 0.0.0.0:8800, data in /data` (0.0.0.0 here is **inside** the container; the outside is limited to the loopback by compose), then one line per request, for example `127.0.0.1 "GET /health HTTP/1.1" 200 -`. Docker's own health check calls `/health` every minute, so you will see that line every minute: it is normal.

```bash
docker stats --no-stream arkan-monitoring-ingest
```

**Expected:** `MEM USAGE / LIMIT` well under `96MiB`, for example `20MiB / 96MiB` ([../VPS-MEMORY.md](../VPS-MEMORY.md) estimates 25 to 40 MB in normal running).

### B17. Prepare the data folder and the alarm register: `manage.py init`

`manage.py` is the admin tool. You run it **inside the container** with `docker compose exec ingest python tools/manage.py <command>`: `exec` runs a command in the running container, `ingest` is the service name, and inside the container the data folder is `/data`.

**Where:** VPS, user ai, in `/opt/arkan-monitoring/server`.

```bash
docker compose exec ingest python tools/manage.py init
```

**Expected:**

```text
alarm register copied to /data/alarm-register.csv (edit it in Excel; changes apply at once)
data folder ready: /data
```

`/data/alarm-register.csv` inside the container is `/srv/arkan-monitoring/data/alarm-register.csv` on the VPS: **the register in use**, the copy you will edit (section C6). `init` never overwrites it: run a second time, it prints only `data folder ready: /data`.

### B18. Add the site

The Adab values (owner, 7 November 2026): PLN 3-phase, 82.5 kVA contract, 200 A main breaker. They set the thresholds of A08 (high demand), A37 (phase current near the PLN limit) and A29 (phase current near the rating). **Do not forget them**: without them those three alarms stay silent.

**Where:** VPS, user ai, in `/opt/arkan-monitoring/server`.

```bash
docker compose exec ingest python tools/manage.py add-site adab --name "Adab hotel" --contracted-kva 82.5 --rated-a 200 --lat -8.4766 --lon 115.4319
```

**Expected:** `site adab created: /data/sites/adab/site.json`.

Other options exist (defaults are right for Adab): `--tz Asia/Makassar`, `--utc-offset 8`, `--nominal-v 230`. **If** it says `exists already: edit it by hand`, the site was made before; check it:

```bash
cat /srv/arkan-monitoring/data/sites/adab/site.json
```

**Expected:** JSON with `"name": "Adab hotel"`, `"timezone": "Asia/Makassar"`, `"contracted_kva": 82.5`, `"contract_v_ln": 220`, `"rated_a": 200.0`, `"nominal_v": 230.0`, the `labels` of each value and the `live` list. These values and labels can be edited later in this file with `nano` (keep a copy first, see C6 for the method).

### B19. Add the logger: `add-device` (owner runs it, or is present)

This command prints two secrets **once**:
- the **token** of `LOG-0001`: the logger's password for the VPS;
- the **setup WiFi password** (`portal_pass`): the password of the logger's own setup WiFi `ARKAN-LOG-0001`, used on site (tutorial 1).

**Before running it, decide** whether you also want the **SD card settings file** (a small text file that sets up the logger from its SD card, used in tutorial 1). It can only be made now, together with the token. If unsure, make it: it is easy to delete.

**Have the password manager open** (**to verify**: which password manager the company uses). Make an entry named for example `arkan-monitoring LOG-0001 (adab)` with fields `token`, `portal_pass`, the date and who made it.

**Where:** VPS, owner (no sudo needed), in `/opt/arkan-monitoring/server`. Without the SD file:

```bash
docker compose exec ingest python tools/manage.py add-device adab LOG-0001
```

Or, with the SD file (use only one of the two commands):

```bash
docker compose exec ingest python tools/manage.py add-device adab LOG-0001 --sd-settings /data/export/settings-LOG-0001.txt
```

**Expected:**

```text
device LOG-0001 added to site adab
TOKEN (shown once, keep it secret): <32 characters>
SETUP WIFI PASSWORD for ARKAN-LOG-0001 (portal_pass, keep it with the token): <12 characters>
```

and, with the SD option, `SD card settings file written: /data/export/settings-LOG-0001.txt`.

Straight away:
1. Copy the token and the setup WiFi password into the password manager entry. Check them character by character.
2. Clear the screen so they do not stay visible:

```bash
clear
```

Where they must **never** go: WhatsApp, email, a git repository, a document, a screenshot, a ticket. Only the token's hash is kept on the VPS (`devices.json`), so nobody can read it back.

**If** it says `LOG-0001 exists already ... use rotate-token`: the logger was added before. If its token is lost, see section C10.

### B20. Optional: get the SD settings file off the VPS safely

Skip this if you did not use `--sd-settings`. The file holds the token **in clear**: it must not stay on the VPS.

**Where:** Laptop (PowerShell), in your working folder:

```powershell
Set-Location $env:USERPROFILE\arkan
```

```powershell
scp hermes-vps:/srv/arkan-monitoring/data/export/settings-LOG-0001.txt .
```

**Expected:** `settings-LOG-0001.txt 100% ...`. **If** `Permission denied`: `ai` is not uid 1000 (B1); the owner copies the file for you.

Check it arrived complete:

```powershell
Get-Content .\settings-LOG-0001.txt
```

**Expected:** comment lines, then `dev_id=LOG-0001`, `dev_token=...`, `srv_url=https://arkan-monitoring.duckdns.org`, `portal_pass=...`, and commented WiFi lines (filled in tutorial 1).

Then delete it on the VPS. **Where:** VPS, user ai.

```bash
ls -l /srv/arkan-monitoring/data/export/settings-LOG-0001.txt
```

```bash
rm /srv/arkan-monitoring/data/export/settings-LOG-0001.txt
```

**Expected:** `ls` shows the file once, `rm` prints nothing. On the laptop, keep the file only until it is on the SD card (tutorial 1), then delete it:

```powershell
Remove-Item .\settings-LOG-0001.txt
```

### B21. The Caddy site file, block by block

Read [monitoring.caddy](../../server/deploy/monitoring.caddy) before the owner installs it. What each block does:

| Block | What it does |
|---|---|
| `arkan-monitoring.duckdns.org { ... }` | Everything inside applies to this name only. Caddy gets the HTTPS certificate for it automatically and redirects `http://` to `https://` |
| `encode gzip` | Compresses the answers (faster pages) |
| `header { ... }` | Security headers on every answer: `Strict-Transport-Security` (browsers use HTTPS only), `X-Robots-Tag "noindex, nofollow"` (search engines do not list the site), `X-Content-Type-Options "nosniff"`, and `-Server` removes the server name |
| `@device { path /api/v1/ingest /api/v1/ota /api/v1/firmware/* /api/v1/config /api/v1/config/report /api/v1/registers }` | A **matcher**: a name for "requests to the logger paths" |
| `@livepost { method POST  path /api/v1/live }` | A matcher for the logger's live snapshots (POST only) |
| `handle @device { request_body { max_size 256KB } reverse_proxy 127.0.0.1:8800 }` | Logger paths: **no web login** (a logger cannot type one; the service checks the token), body limited to 256 KB, then passed to our container |
| `handle @livepost { request_body { max_size 16KB } reverse_proxy 127.0.0.1:8800 }` | Same for live snapshots, limited to 16 KB |
| `handle { basicauth { import /opt/edge/secrets/hub-users.caddy  import /opt/edge/secrets/monitoring-users.caddy } redir / /live/ 302  reverse_proxy 127.0.0.1:8800 { header_up X-Auth-User {http.auth.user.id} } }` | **Everything else** (the site page `/live/<site>/` and its register page, `/api/v1/status`, `GET /api/v1/live/<site>`, `/api/v1/alarms/<site>`, `/api/v1/history/<site>`, the admin API `/api/v1/admin/...`, `/health`): **Arkan login first** (the shared login file), then `/` is sent to `/live/` until OED takes `/`, then passed to the container with the user's name in `X-Auth-User` (the service uses it for `ADMIN_USERS` and writes it in the register history) |
| `log { output file /var/log/caddy/arkan-monitoring.log { roll_size 10mb  roll_keep 5 } format filter { ... } }` | Access log of our site, at most 5 files of 10 MB, with the `Authorization` (token or password) and `Cookie` headers **deleted** before writing |

A `handle` block with a matcher wins over the plain `handle` block, so the logger paths never meet the login.

### B22. Install the site file, validate, reload (owner)

**Where:** VPS, owner with sudo. First the login file for this platform only, which the site file imports. It holds one comment line and has the same owner and rights as the Arkan login file; the logins go in later ([../LIVE.md](../LIVE.md#logins)). Not empty: Caddy 2.6 refuses to import an empty file (`Could not read tokens ... EOF`):

```bash
echo '# Logins for this platform only (technicians), one line per login: <name> <hash>. docs/LIVE.md "Logins".' | sudo tee /opt/edge/secrets/monitoring-users.caddy
```

```bash
sudo chown --reference=/opt/edge/secrets/hub-users.caddy /opt/edge/secrets/monitoring-users.caddy
```

```bash
sudo chmod --reference=/opt/edge/secrets/hub-users.caddy /opt/edge/secrets/monitoring-users.caddy
```

Then copy the site file (`-n`: never overwrite an existing file):

```bash
sudo cp -n /opt/arkan-monitoring/server/deploy/monitoring.caddy /opt/edge/sites/monitoring.caddy
```

**Expected:** no output. Check that the copy is identical to the repository file:

```bash
diff /opt/arkan-monitoring/server/deploy/monitoring.caddy /opt/edge/sites/monitoring.caddy
```

**Expected:** no output (no difference). **If** lines are shown, a `monitoring.caddy` already existed and `cp -n` kept it: stop and compare with the owner.

If the port is not 8800 (B14), the owner edits the three `reverse_proxy 127.0.0.1:8800` lines of `/opt/edge/sites/monitoring.caddy` now.

Check that the whole Caddy configuration, with the new file, is valid (the path is the one found in B8):

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

**Expected:** some log lines, then `Valid configuration`. **If** it shows an error with a file name and line number, nothing has changed on the live site yet: fix that line (owner) and validate again.

**The owner approves the reload**, then:

```bash
sudo systemctl reload caddy
```

**Expected:** no output. Check Caddy is still running:

```bash
systemctl status caddy --no-pager
```

**Expected:** `Active: active (running)`. If a reload fails, Caddy keeps the previous configuration running, so the other sites stay up. The error is then in the Caddy journal (owner; **to verify** that Caddy logs to the journal on hermes-vps):

```bash
sudo journalctl -u caddy --no-pager -n 50
```

In the first minute after the reload, Caddy asks Let's Encrypt for the certificate of `arkan-monitoring.duckdns.org`.

### B23. Checks from the laptop with curl.exe

**Where:** Laptop (PowerShell). Each check prints the HTTP status code (a 3-digit answer: 200 = OK, 401 = login or token needed, 404 = not found, 502 = Caddy cannot reach the service).

1. The live page asks for the Arkan login:

```powershell
curl.exe -s -o NUL -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/live/
```

**Expected:** `401`.

2. The start page also asks for the login (then redirects to `/live/`):

```powershell
curl.exe -s -o NUL -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/
```

**Expected:** `401`.

3. The status API asks for the login:

```powershell
curl.exe -s -o NUL -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/api/v1/status
```

**Expected:** `401`.

4. The ingest path is open to loggers but refuses a request without a token. This answer comes **from our service** (with a JSON message), which proves Caddy passed it through without asking for the web login:

```powershell
curl.exe -s -X POST -w "\n%{http_code}\n" https://arkan-monitoring.duckdns.org/api/v1/ingest
```

**Expected:**

```text
{"ok": false, "error": "unknown or missing device token"}
401
```

**If** you get `401` with **no JSON line**, the 401 comes from Caddy's login: the `@device` block is not working (B21, B22).

5. Plain `http://` is redirected to `https://`:

```powershell
curl.exe -s -o NUL -w "%{http_code}\n" http://arkan-monitoring.duckdns.org/live/
```

**Expected:** `308` (Caddy's permanent redirect).

6. Port 8800 is **not** reachable from the internet:

```powershell
Test-NetConnection arkan-monitoring.duckdns.org -Port 8800
```

**Expected** (after up to 20 seconds): a warning `TCP connect to ... failed` and `TcpTestSucceeded : False`. **If `True`: stop and call the owner** (Part E).

7. The service answers through Caddy with your login (curl asks for the password; type it, nothing shows while typing):

```powershell
curl.exe -s -u <hub-user> https://arkan-monitoring.duckdns.org/health
```

**Expected:** `{"ok": true, "version": "0.4.0", "time": "..."}`.

**If any check gives an error like `schannel: ...` or `SSL certificate problem`**, the certificate is not there yet: wait two minutes and try again, then see Part D, "Certificate not issued". **If** a check gives `502`, see Part D.

### B24. First login in the browser

1. Open https://arkan-monitoring.duckdns.org/ in Chrome, Edge or Firefox.
2. The browser shows its own small sign-in box. Type your Arkan dashboard login (`<hub-user>` and its password, from the owner).
3. **Expected:** the page moves to `/live/`: the Arkan side bar on the left, the title `All sites` with the time, and a table with the columns `Site`, `Logger`, `Power now`, `Live`, `Last record (UTC)`, `Firmware`, and one row: `adab`, `LOG-0001`, `–`, `none` (in red), `–`, `–`. Nothing has been received yet: that is correct.
4. Click `adab`. **Expected:** the site page `/live/adab/`: in the side bar `Adab hotel`, **View as** with your login, the menu (**Live now**; **History**: Power, One day, Energy per day, This week vs last, Temperature, Humidity; **Power quality**; **Weather**; **Logger**: Meter registers, Firmware versions, and Firmware update if your login is in `ADMIN_USERS`; **Platform**: All sites), **Settings** and a red pill `No live data` at the bottom, and in the page the message `No live data for this site (logger offline or not installed yet).` (the open alarms and the alarm log are still shown). The history pages say there is nothing yet.
5. Check the padlock next to the address: it should say the connection is secure.

**If** the sign-in box keeps coming back, the login is wrong or not in `hub-users.caddy` (or `monitoring-users.caddy`): ask the owner.

### B25. Test with the simulated logger (from the laptop)

[simulate_logger.py](../../server/tools/simulate_logger.py) sends exactly what the real logger sends: the same CSV records and the same live snapshots, with the token of `LOG-0001`. It lets you test the whole chain (internet, Caddy, service, files, alarms, live page) before the board exists.

The options used here:
- `--backlog-hours 3`: first sends the **last 3 hours** of records in batches of 60, as a logger does after an outage;
- `--resend`: sends the last batch twice; the second time the service must count **duplicates** and store nothing;
- `--event dip`: 30 minutes into the backlog, simulates 6 minutes of low voltage on L2, which must give a **voltage dip** (A26) and an **undervoltage** (A05) in the alarm log;
- `--live`: then keeps going like a real logger: a live snapshot every 15 s and a record every minute, until you press Ctrl+C.

Do **not** try `set-config` or `publish-fw` during this test: the real logger would receive those later.

**Where:** Laptop (PowerShell). Get the simulator from the VPS (the same version as the tag installed):

```powershell
Set-Location $env:USERPROFILE\arkan
```

```powershell
scp hermes-vps:/opt/arkan-monitoring/server/tools/simulate_logger.py .
```

Put the token in a variable without it appearing on screen or in the PowerShell history (paste the token from the password manager when asked):

```powershell
$tok = Read-Host "Token of LOG-0001"
```

Run the simulator:

```powershell
python .\simulate_logger.py --url https://arkan-monitoring.duckdns.org --token $tok --backlog-hours 3 --resend --event dip --live
```

**Expected** (times are yours; this was a test run):

```text
batch 1: 60 rows 2026-11-07T03:18:00Z -> HTTP 200 {"ok": true, "stored": 60, "duplicates": 0, "rejected_rows": 0, "last_ts": "2026-11-07T04:17:00Z", "alarms": 6}
batch 2: 60 rows 2026-11-07T04:18:00Z -> HTTP 200 {"ok": true, "stored": 60, "duplicates": 0, "rejected_rows": 0, "last_ts": "2026-11-07T05:17:00Z", "alarms": 0}
batch 3: 60 rows 2026-11-07T05:18:00Z -> HTTP 200 {"ok": true, "stored": 60, "duplicates": 0, "rejected_rows": 0, "last_ts": "2026-11-07T06:17:00Z", "alarms": 1}
same batch again -> HTTP 200 {"ok": true, "stored": 0, "duplicates": 60, "rejected_rows": 0, "last_ts": "2026-11-07T06:17:00Z", "alarms": 0} (expect stored 0, duplicates 60)
live: snapshot every 15 s, record every minute (Ctrl-C to stop)
live 2026-11-07T06:18:56Z -> HTTP 204
record 2026-11-07T06:18:00Z -> HTTP 200 {"ok": true, "stored": 1, "duplicates": 0, "rejected_rows": 0, "last_ts": "2026-11-07T06:18:00Z", "alarms": 0}
live 2026-11-07T06:19:00Z -> HTTP 204
```

What to check: 3 batches with `"stored": 60` each, `"rejected_rows": 0`, the resent batch with `"stored": 0, "duplicates": 60`, then `HTTP 204` (accepted, nothing to say) for each live snapshot.

**Leave it running** and go to B26 in a second PowerShell window (or in the browser).

**If different:**
- `HTTP 401 ... unknown or missing device token`: the token is wrong (a character missing?). Run the `Read-Host` line again.
- `HTTP 401` with an empty body: Caddy asked for a login (B23 check 4).
- `urlopen error` or `CERTIFICATE_VERIFY_FAILED`: certificate problem (Part D).
- `rejected_rows` above 0 or `HTTP 400`: Part D, "400 or rejected rows".

### B26. Check the results

**1. The live page.** In the browser, open https://arkan-monitoring.duckdns.org/live/adab/.

**Expected:** within 15 s, the green pill `Live · updated N s ago` and `Hotel time HH:MM` in the header; the **Open alarms** card with `✓ No open alarm` and the line `Meter EM01 · Modbus connected` (green, `for N s, since HH:MM`); the cards **Power** (`Total power`, `Apparent power` with `% of the 82.5 kVA PLN contract`, `Power factor`, `Frequency`), **Per phase** (`Voltage L-N (V)` and `Current (A)`, L1 L2 L3 in each), **Environment** (`Electrical room temperature`, `Outdoor temperature`, humidity, room minus outdoor, outdoor dew point), each with a small line graph that grows every 15 s; then **Logger** (`LOG-0001`, WiFi signal `-63 dBm`, upload backlog `0 min`, SD card `OK`, firmware `sim-0.5.0`) and `Alarm log · last 20, hotel time`. Click **Power** and **Energy per day** in the menu: the hours sent by the simulator are there. Click **Power quality**: `Dips · swells` shows `6 · 0` in red, and the table *Power quality alarms* has the lines of the simulated dip (A26 Voltage dip and A05 Undervoltage, start and clear). The overview `/live/` now shows `adab`, `LOG-0001`, the power now, `● N s ago` in green, a last record time, firmware `0.4.0`.

**2. The status of every logger.** Where: VPS, user ai, in `/opt/arkan-monitoring/server`.

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:**

```text
adab: Adab hotel (Asia/Makassar)
  LOG-0001: fw 0.4.0, last record 2026-11-07T06:18:00Z
```

**3. The day file** (one file per UTC day; if the 3 hours crossed midnight UTC, there are two).

```bash
ls -l /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/$(date -u +%Y/%m)/
```

**Expected:** `2026-11-07.csv` (today's UTC date). `$(date -u +%Y/%m)` is replaced by the shell with the current year and month, for example `2026/11`.

```bash
wc -l /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/$(date -u +%Y/%m)/$(date -u +%F).csv
```

**Expected:** about 181 lines (the header plus 180 records) plus one per minute of live run.

```bash
tail -n 2 /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/$(date -u +%Y/%m)/$(date -u +%F).csv
```

**Expected:** two long lines starting with a time like `2026-11-07T06:19:00Z,230.4...`. The columns are explained in [../DATA-FORMAT.md](../DATA-FORMAT.md) section 3.

**4. The alarm log.**

```bash
docker compose exec ingest python tools/manage.py alarms adab
```

**Expected** (your times; local time is WITA):

```text
last lines of /data/sites/adab/alarms/2026.csv:
  ts_utc,local_time,device,id,name,severity,state,value,threshold,unit,duration_min,message
  2026-11-07T03:18:00Z,2026-11-07 11:18,LOG-0001,A02,Power interruption,info,event,,,event,,logger restarted (poweron)
  2026-11-07T03:18:00Z,2026-11-07 11:18,LOG-0001,A16,Backlog growing,warning,start,180,60,min,,oldest unsent record older than 60 min
  2026-11-07T03:47:00Z,2026-11-07 11:47,LOG-0001,A26,Voltage dip,info,start,180,207,V,,a 15 s phase voltage sample below 207 V (-10 %)
  2026-11-07T03:47:00Z,2026-11-07 11:47,LOG-0001,A05,Undervoltage,warning,start,195,207,V,,a phase voltage L-N (1-min mean) below 207 V for 5 min
  2026-11-07T03:53:00Z,2026-11-07 11:53,LOG-0001,A05,Undervoltage,warning,clear,195,207,V,6,cleared after 6 min; worst value 195
  2026-11-07T03:53:00Z,2026-11-07 11:53,LOG-0001,A26,Voltage dip,info,clear,180,207,V,6,cleared after 6 min; worst value 180
  2026-11-07T06:14:00Z,2026-11-07 14:14,LOG-0001,A16,Backlog growing,warning,clear,180,60,min,176,cleared after 176 min; worst value 180
```

How to read it:
- **A02** at the first minute: the simulated logger says it has just been powered on.
- **A16** starts at the first minute: the simulated rows say the oldest unsent record is 180 minutes old (a 3-hour outage); it clears when that falls under 5 minutes, near the end of the backlog.
- **A26 and A05** start 29 minutes after the first minute (the simulated dip), at the **time of the records**, not the time they arrived; they clear 6 minutes later.

No line starts with `OPEN`: no alarm is still open. The same lines appear at the bottom of "Live now" on the site page.

**5. The events of the logger.**

```bash
cat /srv/arkan-monitoring/data/sites/adab/LOG-0001/events.jsonl
```

**Expected:** three JSON lines: `"kind": "device_added"`, `"kind": "firmware"` (from `null` to `0.4.0`), `"kind": "boot"` with `"reason": "poweron@0.4.0"`.

Let the simulator run a few minutes, then stop it in its PowerShell window with **Ctrl+C**, and remove the token from memory:

```powershell
Remove-Variable tok
```

Good to know: if you run the simulator **again** later, the log also gets an A02 (new "boot") and an **A19 Energy counter went backwards** (each run starts its meter counter from the same value). That is normal for the simulator. About 15 minutes after you stop it, **A01 Logger offline** starts: also normal, and a good test of A01.

### B27. Clean the simulated data before the real logger (owner)

The real logger uses the same code `LOG-0001`, so the simulated records must go. The service keeps some things **in memory** (the list of times already stored for recent days, the time of the last upload for A01, the live history). If the files are deleted while it runs, it can wrongly treat new rows with the same times as duplicates, or start a `_2.csv` file. So: **stop the container, delete, start again.** The owner approves the stop and start.

**Where:** VPS, user ai, in `/opt/arkan-monitoring/server`. Check the simulator is stopped (B26), then:

```bash
docker compose stop ingest
```

**Expected:** `Container arkan-monitoring-ingest  Stopped`.

**Where:** VPS, owner with sudo. Look first:

```bash
ls -l /srv/arkan-monitoring/data/sites/adab /srv/arkan-monitoring/data/sites/adab/LOG-0001
```

Delete the simulated records, the alarm state and the alarm log ([../VPS-SETUP.md](../VPS-SETUP.md) step 8):

```bash
sudo rm -rf /srv/arkan-monitoring/data/sites/adab/LOG-0001/raw /srv/arkan-monitoring/data/sites/adab/LOG-0001/alarm-state.json /srv/arkan-monitoring/data/sites/adab/alarms /srv/arkan-monitoring/data/sites/adab/LOG-0001/live /srv/arkan-monitoring/data/sites/adab/LOG-0001/live.json
```

Only if they exist (you ran `daily`, `export-oed` or `set-config` during the test), also:

```bash
sudo rm /srv/arkan-monitoring/data/sites/adab/daily.csv
```

```bash
sudo rm -r /srv/arkan-monitoring/data/export/oed/adab
```

```bash
sudo rm /srv/arkan-monitoring/data/sites/adab/LOG-0001/config.json
```

Keep `events.jsonl`: it records that the test happened.

**Where:** VPS, user ai, in `/opt/arkan-monitoring/server`:

```bash
docker compose start ingest
```

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** `LOG-0001: fw 0.4.0, last record None`. The firmware shown is the simulator's; the real logger replaces it with its own at its first upload. The live page shows `No live data for this site (logger offline or not installed yet).`

### B28. Set up the backups and the daily summary

Do sections [C4](#c4-backups) (backup crontab and a first backup by hand) and [C3](#c3-daily-summary-and-its-cron) (daily summary) now.

### B29. Done: checklist

| Check | Command or place | Expected |
|---|---|---|
| Container healthy | `docker compose ps` | `Up ... (healthy)` |
| Loopback only | `ss -ltn \| grep 8800` | `127.0.0.1:8800` |
| Health | `curl -s http://127.0.0.1:8800/health` | `{"ok": true, ...}` |
| Memory | `docker stats --no-stream arkan-monitoring-ingest` | well under 96 MiB |
| Site and logger | `manage.py list` | `adab`, `LOG-0001`, last record None |
| Register in use | `ls -l /srv/arkan-monitoring/data/alarm-register.csv` | the file exists |
| Secrets | password manager | token and `portal_pass` of LOG-0001 saved; no `settings-*.txt` left in `/srv/arkan-monitoring/data/export/` |
| Caddy | B23 checks | 401, 401, 401, JSON 401, 308, port 8800 closed |
| Browser | `/live/` | login, then the table |
| Firmware update | `/live/adab/`, side menu | **Firmware update** shows for the logins in `ADMIN_USERS` (B14), not for the others |
| Backups | `ls -l /srv/arkan-monitoring/backups/` | one `data-<stamp>.tar.gz` |
| Note for the next person | | the tag installed, the B1 uid result, the answers to every "to verify" |

The VPS is ready for the logger: go to [tutorial 1](1-LOGGER-ON-SITE.md).

---

## Part C. Everyday operations

Unless said otherwise, every command in this part runs on the **VPS, user ai**, after:

```bash
cd /opt/arkan-monitoring/server
```

`docker compose` and `docker compose exec ingest python tools/manage.py ...` only work from that folder.

### C1. Logs: what the service is doing

The last 100 lines:

```bash
docker compose logs --tail 100 ingest
```

Follow it live (Ctrl+C to stop following; the service keeps running):

```bash
docker compose logs -f ingest
```

The last hour only:

```bash
docker compose logs --since 1h ingest
```

**Expected:** one line per request: time, address, request, status code, for example `2026-11-07T06:18:50Z 172.x.x.x "POST /api/v1/ingest HTTP/1.1" 200 -`. The address is an internal Docker address, not the logger's. A healthy logger gives one `POST /api/v1/ingest` per minute and four `POST /api/v1/live` per minute; `127.0.0.1 "GET /health"` every minute is Docker's health check. Tokens are never written. Docker keeps at most 3 files of 10 MB.

The Caddy access log of our site (with the logger's real address) is `/var/log/caddy/arkan-monitoring.log`; reading it may need the owner (**to verify** its permissions).

### C2. Status of every logger

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** each site, then each logger with its firmware and the time of its last record (UTC). A last record more than a few minutes old means the logger is not sending (Part D). A disabled logger shows `DISABLED`.

The same, as JSON, with the age of the last live snapshot in seconds (`live_age_s`):

```bash
curl -s http://127.0.0.1:8800/api/v1/status
```

The open alarms and the last 20 lines of the alarm log (`--lines 50` for more):

```bash
docker compose exec ingest python tools/manage.py alarms adab
```

### C3. Daily summary and its cron

`manage.py daily adab` rebuilds `sites/adab/daily.csv`: one row per **WITA** day (local day of the site), with the minutes received, the coverage, the counts of **dips**, **swells**, **power interruptions** and alarms started, the kWh of the day (`EM01_e_delta`), means, minimum and maximum values with the time of the peak kW and kVA ([../DATA-FORMAT.md](../DATA-FORMAT.md) section 5).

By hand:

```bash
docker compose exec ingest python tools/manage.py daily adab
```

**Expected:** `/data/sites/adab/daily.csv: N day(s); energy columns end in _e_delta (kWh), local time Asia/Makassar; dips, swells, power_interruptions counted from the alarm log`.

Every night automatically, just after midnight WITA. With the owner's OK, add a line to the crontab of user `ai` (it needs the `docker` group):

```bash
crontab -l
```

**Expected:** the current lines, or `no crontab for ai`. Note them: you must not remove any.

```bash
crontab -e
```

The first time, it asks which editor: type the number of `nano` and Enter. Go to the end of the file and add this line (00:20 WITA = 16:20 UTC, if B7 showed the VPS in UTC):

```text
20 16 * * * docker exec arkan-monitoring-ingest python tools/manage.py daily adab >/dev/null
```

Save (Ctrl+O, Enter) and quit (Ctrl+X). **Expected:** `crontab: installing new crontab`. Check with `crontab -l`. The five fields are minute, hour, day of month, month, day of week; `*` means "every".

### C4. Backups

[backup.sh](../../server/deploy/backup.sh) makes one compressed archive of the whole data folder, `/srv/arkan-monitoring/backups/data-<stamp>.tar.gz` (`<stamp>` is the UTC date and time, for example `20261108T0230Z`), keeps the last **14**, and writes one line to `backup.log`.

**Which crontab** (**to verify** with the owner): [../VPS-SETUP.md](../VPS-SETUP.md) section 9 calls it "the owner's crontab". The script must read `/srv/arkan-monitoring/data` and write `/srv/arkan-monitoring/backups`, both owned by uid 1000. So use the crontab of `ai` if `ai` is uid 1000 (B1); otherwise root's crontab, edited by the owner with `sudo crontab -e`.

**1. Run it once by hand** (VPS, user ai):

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**Expected:** `2026-11-07T07:00:00Z backup ok: /srv/arkan-monitoring/backups/data-20261107T0700Z.tar.gz (12K)` (the size grows with the data).

**2. Add the nightly line** (02:30 server time), with the owner's OK:

```bash
crontab -e
```

Add at the end:

```text
30 2 * * * /opt/arkan-monitoring/server/deploy/backup.sh >> /srv/arkan-monitoring/backups/backup.log 2>&1
```

**3. Check, the next morning:**

```bash
tail -n 3 /srv/arkan-monitoring/backups/backup.log
```

**Expected:** a `backup ok` line with last night's date.

```bash
ls -lt /srv/arkan-monitoring/backups/
```

**Expected:** the newest archive on top; never more than 14 archives.

```bash
tar -tzf /srv/arkan-monitoring/backups/data-<stamp>.tar.gz | head
```

**Expected:** the list starts with `data/`, `data/devices.json`, `data/sites/`... (a readable archive).

**4. Test a restore, into a test folder first** (do it once after the install, then every few months). This never touches the real data.

```bash
mkdir ~/restore-test
```

```bash
tar -xzf /srv/arkan-monitoring/backups/data-<stamp>.tar.gz -C ~/restore-test
```

```bash
ls ~/restore-test/data
```

**Expected:** `alarm-register.csv devices.json export firmware logs sites`.

Read the restored copy with the admin tool (on the VPS itself, outside the container; needs `python3` on the VPS, check with `python3 --version`). `list` only reads:

```bash
python3 /opt/arkan-monitoring/server/tools/manage.py --data ~/restore-test/data list
```

**Expected:** the same sites and loggers as `manage.py list`, with a last record from before the backup time.

See what changed since the backup:

```bash
diff -rq ~/restore-test/data /srv/arkan-monitoring/data
```

**Expected:** only today's files differ (today's day file, `alarm-state.json`, `events.jsonl`, the alarm log). Then remove the test folder (check the path first):

```bash
rm -r ~/restore-test
```

**5. A real restore (owner only, with the container stopped).** Only when the data folder is damaged or lost. Nothing is deleted: the current folder is set aside.

```bash
docker compose stop ingest
```

(VPS, user ai, in `/opt/arkan-monitoring/server`, owner approves.) Then, VPS, owner with sudo:

```bash
sudo mv /srv/arkan-monitoring/data /srv/arkan-monitoring/data.before-restore-<date>
```

```bash
sudo tar -xzf /srv/arkan-monitoring/backups/data-<stamp>.tar.gz -C /srv/arkan-monitoring
```

```bash
sudo chown -R 1000:1000 /srv/arkan-monitoring/data
```

Then, VPS, user ai:

```bash
docker compose start ingest
```

```bash
docker compose exec ingest python tools/manage.py list
```

**Expected:** the service is healthy, the last record is from before the backup. The records received after the backup are still on the logger's SD card and in `data.before-restore-<date>` (if readable): bring them back with a backfill (section C9), then rebuild the alarm log (C6).

### C5. Updating to a new tag, and going back

The VPS only runs tags. An update restarts the container: **the owner approves.** The same steps, with the tagging on GitHub and the logger updates: [`../HOW-TO-UPDATE.md`](../HOW-TO-UPDATE.md).

> **Three things that went wrong on 8 November 2026** ([`../UPDATING.md`](../UPDATING.md) section 5): (1) `/opt/arkan-monitoring` must be a git clone; if `git describe` says `fatal: not a git repository`, the code was copied by hand: stop and ask the owner (B11 makes the clone). (2) Run every `docker compose` command in `/opt/arkan-monitoring/server`; elsewhere it says `no configuration file provided`. (3) Never `docker rm -f` the container: if `/health` gives no answer and `docker compose ps` lists nothing, `docker compose up -d --build` in that folder creates it again; the data stays in `/srv/arkan-monitoring/data`.

**1. Note the current tag:**

```bash
cd /opt/arkan-monitoring
```

```bash
git describe --tags --always
```

**Expected:** for example `v0.4.0`. Write it down: it is `<previous-tag>`.

**2. Make a backup by hand** (C4 step 1):

```bash
/opt/arkan-monitoring/server/deploy/backup.sh
```

**3. Get the new tags and check the working copy is clean:**

```bash
git fetch --tags
```

```bash
git status
```

**Expected:** `HEAD detached at <previous-tag>` and `nothing to commit, working tree clean` (an untracked `server/.env` is fine). **If** files are listed as modified, someone edited the code on the VPS: stop and ask the owner.

Check which commit the new tag points to before you use it (on 10 November a wrong `v0.6.0` was on GitHub for a few minutes):

```bash
git log -1 --oneline <tag>
```

**Expected:** the release commit, a line like `cae7b85 (tag: v0.7.0) Release v0.7.0: ...`. **If** it is another commit, the tag was moved on GitHub: run `git fetch --tags --force` and check again. Still not the release commit: stop and ask the owner.

```bash
git checkout <tag>
```

**Expected:** `HEAD is now at ...`. Read the release notes of the new tag (on GitHub) for any extra step.

**3a. New settings in `.env`?** Compare the setting names of the example with yours:

```bash
cd /opt/arkan-monitoring/server
```

```bash
grep -oE '^[A-Z_]+=' .env.example | sort > /tmp/env-new; grep -oE '^[A-Z_]+=' .env 2>/dev/null | sort > /tmp/env-mine; comm -23 /tmp/env-new /tmp/env-mine; rm /tmp/env-new /tmp/env-mine
```

**Expected:** no output. **If** names are printed (for example `ADMIN_USERS=` the first time you update to `v0.4.0`), add them to `.env` as in B14 (`cp -n .env.example .env` first if you have no `.env` at all).

**3b. Did the Caddy site file change?**

```bash
diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy && echo same
```

**Expected:** `same`. (Once OED is installed, compare with `server/deploy/oed/monitoring-oed.caddy` instead.) **If** lines are printed (for example `/api/v1/registers` added to the `@device` line in `v0.4.0`), the owner installs the new file, validates it and reloads Caddy exactly as in B22, **after** step 4 below. Without it, a logger cannot fetch a register table sent from the register page: it is asked for the web login and gives up.

**4. Rebuild and restart:**

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

**5. Check:**

```bash
curl -s http://127.0.0.1:8800/health
```

```bash
docker compose ps
```

```bash
docker compose logs --tail 20 ingest
```

**Expected:** `{"ok": true, "version": ...}` (the service version of the new tag, for example `0.4.0`), `Up ... (healthy)` after a minute, and the logger's `POST /api/v1/ingest 200` lines coming back. The logger kept its records on the SD card during the restart, so nothing is lost.

**Going back (rollback)** if anything is wrong:

```bash
cd /opt/arkan-monitoring
```

```bash
git checkout <previous-tag>
```

```bash
cd /opt/arkan-monitoring/server
```

```bash
docker compose up -d --build
```

Then the same checks. The data folder is not changed by a code update, so going back is safe unless the release notes say the data format changed.

Do not run `docker system prune` or `docker image prune` to clean old images: they act on every service of the VPS. Ask the owner.

### C6. Editing the alarm register in Excel

The register `/srv/arkan-monitoring/data/alarm-register.csv` says which alarms exist, their thresholds, delays, severity, and which will go to WhatsApp (column `whatsapp`, used from session S6). Columns and meaning: [../alarms/README.md](../alarms/README.md) section 4. The service reads it again at the next record after a change: **no restart.**

**1. Download it.** Laptop (PowerShell), in `$env:USERPROFILE\arkan`:

```powershell
scp hermes-vps:/srv/arkan-monitoring/data/alarm-register.csv .\alarm-register.csv
```

**2. Edit it in Excel.** Change only the cells you need (usually `threshold`, `clear_at`, `delay_min`, `severity`, `whatsapp`, `enabled`). Never change `id`, `rule` or `applies_to` unless you know the list in [alarms.py](../../server/app/alarms.py). Save with File, Save As, type **CSV UTF-8 (Comma delimited) (\*.csv)**.

**Warning, to verify on your laptop:** with Indonesian (or other) regional settings, Excel may split columns with `;` and write decimals with `,`. The service reads only `,` between columns and `.` in numbers: a file saved with `;` makes **every alarm disappear**. Check the saved file:

```powershell
Get-Content .\alarm-register.csv -TotalCount 3
```

**Expected:** `id,name,group,rule,applies_to,threshold,clear_at,unit,delay_min,severity,whatsapp,repeat_h,enabled,evaluated_on,condition,note` then lines like `A01,Logger offline,logger,offline,logger,15,,min,0,critical,yes,6,yes,...`. **If** you see `;` or numbers like `0,5`: do not upload; save again with comma settings, or edit the file in Notepad instead.

**3. Upload it under a new name** (never overwrite directly):

```powershell
scp .\alarm-register.csv hermes-vps:/srv/arkan-monitoring/data/alarm-register.new.csv
```

**4. Compare** (VPS, user ai). `--strip-trailing-cr` ignores the Windows line ends Excel adds:

```bash
diff --strip-trailing-cr /srv/arkan-monitoring/data/alarm-register.csv /srv/arkan-monitoring/data/alarm-register.new.csv
```

**Expected:** only the lines you changed, shown with `<` (old) and `>` (new). **If** every line is shown, the separators changed: go back to step 2.

**5. Keep the old one and put the new one in place** (show the diff to the owner first; this replaces the register in use):

```bash
cp -n /srv/arkan-monitoring/data/alarm-register.csv /srv/arkan-monitoring/data/export/alarm-register-before-<date>.csv
```

```bash
mv /srv/arkan-monitoring/data/alarm-register.new.csv /srv/arkan-monitoring/data/alarm-register.csv
```

**Expected:** no output. The next record uses the new values.

**A change for one site only.** A file `/srv/arkan-monitoring/data/sites/adab/alarm-register.csv` holds the header line plus only the lines to change for Adab; a line with the same `id` replaces the main line for that site. Make it in Excel with the header and the whole changed line (all columns, `enabled` = `yes`, or the line turns the alarm off), check it as in step 2, then:

```bash
ls -l /srv/arkan-monitoring/data/sites/adab/alarm-register.csv
```

**Expected:** `No such file or directory` (if it exists, download it and edit it instead). Then, on the laptop:

```powershell
scp .\alarm-register-adab.csv hermes-vps:/srv/arkan-monitoring/data/sites/adab/alarm-register.csv
```

**Rebuilding the alarm log.** To see what the new thresholds would have given on all past records (or after a backfill, C9), the log can be replayed. It **deletes and rewrites** `sites/adab/alarms/*.csv`. The two alarms that do not come from the records, **A01 Logger offline** and **A18 Clock wrong**, cannot be replayed: their lines and open states are **kept** as they were. Keep a copy of the log first:

```bash
cp -n /srv/arkan-monitoring/data/sites/adab/alarms/2026.csv /srv/arkan-monitoring/data/export/alarms-2026-before-rebuild-<date>.csv
```

Stop the service during the rebuild (owner approves), so no upload is evaluated at the same time. The logger keeps its records on the SD card meanwhile and sends them when the service is back, so nothing is lost:

```bash
docker compose stop ingest
```

Run the rebuild in a one-off container (same image, same data folder):

```bash
docker compose run --rm ingest python tools/manage.py alarms adab --rebuild
```

**Expected:** `alarm log rebuilt: N line(s)`, then the open alarms and the last lines. Start the service again:

```bash
docker compose start ingest
```

### C7. Remote settings for a logger

The logger asks the VPS every 15 minutes (`rcfg_check_m`) whether new settings are waiting. The list of settings and their meaning: [../FIRMWARE.md](../FIRMWARE.md).

Ask for new settings (example from [../VPS-SETUP.md](../VPS-SETUP.md): TH1 temperature offset -1.2 C, daily reboot at 19:05 UTC = 03:05 WITA):

```bash
docker compose exec ingest python tools/manage.py set-config LOG-0001 th1_off_t=-1.2 reboot_hr=19
```

**Expected:**

```text
settings version 1 for LOG-0001: the logger takes it at its next check (15 min, or console 'config')
it restarts if anything changed; check with show-config
```

Put a setting back to the logger's default with the value `@default`, for example `th1_off_t=@default`.

Check what was asked and what the logger reported after its restart:

```bash
docker compose exec ingest python tools/manage.py show-config LOG-0001
```

**Expected:** `asked by the platform:` with the version and settings, then `reported by the logger at <time>: fw ..., settings version 1, ...` and every setting (secrets shown only as `(set)`). Before the logger has applied it, the reported version is the old one.

**From the browser:** the register page `/live/adab/register` (side menu of the site page, **Meter registers**) sends the meter link settings `meters`, `mb_baud`, `mb_format`, `ct_mult` the same way, and the meter register table itself (firmware 0.4.0 or later). Steps: [../meter/README.md](../meter/README.md#changing-the-register-table). By command: `manage.py set-registers LOG-0001 <file.csv> --comment "..."`, `manage.py show-registers LOG-0001`.

**What is refused, and why:**
- `dev_id`, `dev_token`, `srv_url`, `tls_verify`, `wifi_ssid`, `wifi_pass`, `wifi_ssid2`, `wifi_pass2`, `portal_pass`: **never remotely**, because a wrong value would cut the logger off for good. Message: `error: <key> cannot be changed remotely (it could cut the logger off): use the setup portal on site`.
- A name the logger did not report: `error: <key>: not a setting of this logger (see show-config)`. This protects against typing mistakes, but only once the logger has reported its settings: **before its first report, any name is accepted**, so check the spelling against [../FIRMWARE.md](../FIRMWARE.md).

### C8. Publishing a firmware for OTA

> **Easier way:** **Firmware update** in the side menu of the site page `/live/adab/` sends a GitHub release or a `.bin` from your computer to one logger, with the same checks. Setup (`ADMIN_USERS` in `server/.env`) and use: [../OTA.md](../OTA.md). The steps below are the command-line way.

OTA (over the air): the logger downloads a new firmware from the VPS by itself. With `ota_on=1` (the default) it asks every 6 hours (`ota_check_h`), and at once (within a minute) when it is online and a firmware waits for it. Building the firmware file is covered in [../FIRMWARE.md](../FIRMWARE.md) and tutorial 1 (PlatformIO writes it to `firmware/.pio/build/logger/firmware.bin`: **to verify** on your build).

**1. Upload the file under a new name** (Laptop, PowerShell, in the folder that holds `firmware.bin`; `0.4.2` is an example version):

```powershell
scp .\firmware.bin hermes-vps:/srv/arkan-monitoring/data/firmware-upload-0.4.2.bin
```

**2. Publish it**, first for `LOG-0001` only (VPS, user ai, in `/opt/arkan-monitoring/server`):

```bash
docker compose exec ingest python tools/manage.py publish-fw /data/firmware-upload-0.4.2.bin --device LOG-0001
```

**Expected:** `logger-0.4.2.bin (usb build) offered to LOG-0001. Loggers with ota_on=1 take it within a minute if they are online (live hint), else at their next check (6 h, or console 'ota').` Without `--device`, it is offered to every logger (`offered to every logger`). The version is read from the file (`--version`, if you add it, is only checked against it); a file that is not the logger firmware is refused (`error: ...`).

**3. Remove the uploaded copy** (it was copied into `firmware/`):

```bash
rm /srv/arkan-monitoring/data/firmware-upload-0.4.2.bin
```

**4. Check within 6 hours:** `manage.py list` shows `fw 0.4.2`, and the alarm log shows **A35 Firmware updated** with `firmware 0.4.1 -> 0.4.2, by remote update (OTA)`. **A36 Firmware update rolled back** means the new firmware kept restarting and the logger went back to the old one: do not publish it to other loggers.

Rules:
- **Never publish the same version number with other content**: `publish-fw` refuses if `firmware/logger-<version>.bin` exists with different bytes (the loggers already offered it check its MD5). Build again with a new `FW_VERSION`. A logger is only offered a version **newer** than its own (a logger flashed by hand with a newer firmware is never downgraded). For a deliberate step back to an older version, add `--force`.

### C9. SD card backfill

If the VPS missed records (a long outage, a restore), the logger's SD card still has them. "Backfill" merges them in: rows already on the VPS are skipped, the others are put in time order.

1. On site or at the office, copy the SD card's `/data` folder to the laptop (tutorial 1). Copy only `/data`, not `/config`.
2. Check on the VPS that the target folder does not exist yet:

```bash
ls -ld /srv/arkan-monitoring/data/export/sd-LOG-0001
```

**Expected:** `No such file or directory`.

3. Upload (Laptop, PowerShell; `E:\data` is the copy of the card's `/data` folder, use your path):

```powershell
scp -r E:\data hermes-vps:/srv/arkan-monitoring/data/export/sd-LOG-0001
```

4. Merge (VPS, user ai, in `/opt/arkan-monitoring/server`). Stop the service first (owner approves): it keeps an index of the stored timestamps in memory, and files changed under it could lead to rows counted twice or dropped. The logger keeps its records on the SD card meanwhile and sends them when the service is back.

```bash
docker compose stop ingest
```

```bash
docker compose run --rm ingest python tools/manage.py backfill adab LOG-0001 /data/export/sd-LOG-0001
```

**Expected:** one line per day file, for example `  2026-11-07.csv: 120 new, 1320 already there, 0 bad`, then `backfill done: N new row(s), M duplicate(s), 0 bad row(s)` and, if rows were added, `older rows are not in the alarm log yet: run  manage.py alarms adab --rebuild`.

5. With the service still stopped, put the added rows in the alarm log:

```bash
docker compose run --rm ingest python tools/manage.py alarms adab --rebuild
```

Start the service again:

```bash
docker compose start ingest
```

Then the daily summary:

```bash
docker compose exec ingest python tools/manage.py daily adab
```

6. Remove the uploaded copy (check the path first):

```bash
rm -r /srv/arkan-monitoring/data/export/sd-LOG-0001
```

### C10. Token rotation and disabling a logger

**New token** (lost token, or a token seen by someone who should not have it). The old token stops working **at once**, so the logger cannot upload until it has the new one; it keeps its records on the SD card and sends them afterwards. The new token can only be set **on site** (console or setup portal: tutorial 1), never remotely. Owner runs it, or is present:

```bash
docker compose exec ingest python tools/manage.py rotate-token LOG-0001
```

**Expected:** `NEW TOKEN for LOG-0001 (shown once): <token>` and `Set it on the logger: console 'set dev_token ...' then 'reboot', or the setup portal.` Save it in the password manager entry (replace the old one), then `clear`.

**Stop a logger** (stolen, removed, misbehaving): its uploads get `401`, and A01 is no longer checked for it. Its data stays.

```bash
docker compose exec ingest python tools/manage.py disable-device LOG-0001
```

**Expected:** `LOG-0001 disabled`; `manage.py list` shows `DISABLED`. Allow it again (same token as before):

```bash
docker compose exec ingest python tools/manage.py enable-device LOG-0001
```

**Expected:** `LOG-0001 enabled`.

### C11. Reading the data from the laptop

Everything is plain CSV and JSON: copy it and open it in Excel, or read it with any tool. The site folder holds no token.

The whole site (Laptop, PowerShell, in `$env:USERPROFILE\arkan`):

```powershell
scp -r hermes-vps:/srv/arkan-monitoring/data/sites/adab .\adab-<date>
```

One day of records:

```powershell
scp hermes-vps:/srv/arkan-monitoring/data/sites/adab/LOG-0001/raw/2026/11/2026-11-07.csv .
```

The daily summary:

```powershell
scp hermes-vps:/srv/arkan-monitoring/data/sites/adab/daily.csv .
```

Remember: day files are **UTC** days (`2026-11-07.csv` runs from 08:00 WITA on the 7th to 07:59 WITA on the 8th); `daily.csv` uses WITA days.

### C12. Export for Open Energy Dashboard

```bash
docker compose exec ingest python tools/manage.py export-oed adab --from 2026-11-01
```

**Expected:** `5 file(s) in /data/export/oed/adab (header row: yes; *-energy files: cumulative=yes)`: `adab-EM01-energy.csv`, `adab-TH1-temp.csv`, `adab-TH1-hum.csv`, `adab-TH2-temp.csv`, `adab-TH2-hum.csv`, on the VPS in `/srv/arkan-monitoring/data/export/oed/adab/`. Other options: `--to <date>`, `--all` (every value), `--out <folder>`. How to load them into OED, and where OED plugs into Caddy (`/`), is in [tutorial 3](3-OPEN-ENERGY-DASHBOARD.md).

### C13. Watching disk and memory (once a week)

```bash
df -h /
```

```bash
du -sh /srv/arkan-monitoring/data /srv/arkan-monitoring/backups
```

```bash
free -h
```

```bash
docker stats --no-stream
```

**Expected:** `Use%` under 85 %; the data folder grows by about 20 MB a month per logger; the backups stay at 14 archives; `arkan-monitoring-ingest` under 96 MiB; the other services as usual. Write the figures in the team's log to see the trend. Check also that no old file stays in `/srv/arkan-monitoring/data/export/`:

```bash
ls -la /srv/arkan-monitoring/data/export/
```

---

## Part D. Troubleshooting

Run the diagnosis commands on the **VPS, user ai, in `/opt/arkan-monitoring/server`**, unless "laptop" is written.

| Problem | What you see | Diagnose with | Likely cause and fix |
|---|---|---|---|
| **Container does not start** | `docker compose ps` shows `Exited` or `Restarting`, or nothing | `docker compose ps -a`, then `docker compose logs --tail 50 ingest` | `PermissionError: ... '/data/...'`: the data folder is not owned by uid 1000; owner reruns `setup-vps.sh --apply` (B13). `address already in use`: port taken (B6, B14). Build error: no internet for the image; tell the owner |
| **Health check fails** | `docker compose ps` shows `(unhealthy)`, or `curl` gets no answer | `curl -s http://127.0.0.1:8800/health`, then `docker inspect --format '{{json .State.Health}}' arkan-monitoring-ingest` | Service stuck or out of memory (see "Memory" below). Look at the last log lines. Restart with the owner's OK: `docker compose restart ingest` |
| **502 from Caddy** | Browser or curl: `502` | `curl -s http://127.0.0.1:8800/health`; `ss -ltn \| grep 8800`; `grep reverse_proxy /opt/edge/sites/monitoring.caddy` | Container down (above), or Caddy points to another port than the container (B14) |
| **Certificate not issued** | Browser warning, or curl.exe `schannel: ...` / `SSL certificate problem` | Laptop: `nslookup arkan-monitoring.duckdns.org`; laptop: `Test-NetConnection arkan-monitoring.duckdns.org -Port 80` and `-Port 443`; owner: `sudo journalctl -u caddy --no-pager -n 100` | Name does not point to the VPS (B10). Port 80 or 443 blocked by a firewall (**to verify**: Hostinger panel firewall and `sudo ufw status`). Too many failed tries: Let's Encrypt makes you wait (about an hour), then reload again (owner) |
| **401 for the logger** | Logger or simulator: `HTTP 401` | `manage.py list` (is it `DISABLED`?); the body of the answer: JSON `unknown or missing device token` comes from the service, an empty 401 comes from Caddy's login | Wrong or old token (rotated?): set the right one on the logger (C10). Disabled: `enable-device`. Empty 401: the `@device` block of the Caddy file is missing or wrong (B21) |
| **400 or rejected rows** | `HTTP 400` with an `error`, or `HTTP 200` with `"rejected_rows"` above 0 | The answer's `error` text; the logger's own log (tutorial 1); the header line of the file sent | **400** = the whole upload refused: `empty body`, `first column must be ts`, `too many or repeated columns`, `bad column name ...` (header damaged); for a live snapshot `bad JSON`. **413** = more than 256 KB. **403** `token belongs to another device` = the logger's `X-Device` header does not match its token. **Rejected rows** are dropped, not stored: wrong number of fields, a time not of the form `2026-11-07T03:15:00Z` (seconds must be `00`), a time **more than 10 minutes in the future** (logger clock ahead, see A18 below), a year before 2025, or a character other than letters, digits and `_ . : @ + -` |
| **No data arriving** | `manage.py list` shows an old last record; **A01 Logger offline** open | `docker compose logs --since 30m ingest \| grep ingest`; `manage.py alarms adab` | No `POST /api/v1/ingest` lines: the logger does not reach the VPS (WiFi, `srv_url`, DNS, certificate): tutorial 1. Lines with `401`: see above. Nothing at all from anybody: Caddy or DNS (B23 checks) |
| **Disk full** | Errors `No space left on device`; `df -h` above 95 % | `df -h /`; `du -sh /srv/arkan-monitoring/*`; `ls -la /srv/arkan-monitoring/data/export/`; `docker system df` | Leftovers in `export/` (SD copies, OED files): remove them. Backups keep 14 automatically. **Never delete day files in `raw/`.** Anything else: the owner (other services share the disk) |
| **Memory** | VPS slow; container restarted; `docker stats` near 96 MiB | `free -h`; `docker stats --no-stream`; `docker inspect -f '{{.State.OOMKilled}} {{.RestartCount}}' arkan-monitoring-ingest` | `true` = the container hit its 96 MB limit and was stopped (Docker restarts it, the logger resends, nothing is lost). Note the time and the log, tell the owner. Plan and limits: [../VPS-MEMORY.md](../VPS-MEMORY.md) |
| **Alarm log empty** | `manage.py alarms adab` prints nothing, or no `alarms/` folder | `ls -l /srv/arkan-monitoring/data/sites/adab/alarms/`; `head -n 2 /srv/arkan-monitoring/data/alarm-register.csv` | No records yet (normal before the logger). Register saved by Excel with `;`: every alarm disappears (C6 step 2); put back the copy from `export/`. Rows added by a backfill are not evaluated until `alarms adab --rebuild` (C6) |
| **Live page shows no data** | `No live data for this site (logger offline or not installed yet).`, or the red pill `No data for N min` | `curl -s http://127.0.0.1:8800/api/v1/live/adab` (look for `"devices": {}`); `docker compose logs --since 5m ingest \| grep live` | After a restart the page shows the saved snapshots of the last 60 minutes (`sites/adab/LOG-0001/live.json` = the last one; if it is old, the logger stopped sending). No `POST /api/v1/live` lines: the logger does not send live data (tutorial 1). Wrong site code in the address. Note: while there is no live data, the page also hides the open alarms and the log: use `manage.py alarms adab` |
| **Clock alarm (A18)** | **A18 Clock wrong** in the alarm log; or rows rejected as "in the future" | VPS: `timedatectl` (`System clock synchronized: yes`?); the logger's time in `curl -s http://127.0.0.1:8800/api/v1/live/adab` (`"ts"` of `last`) compared with `date -u` | VPS clock not synchronized: owner. Logger clock wrong: NTP or the RTC on the logger ([../FIRMWARE.md](../FIRMWARE.md), tutorial 1). A18 clears by itself when the clocks agree within 1 minute |
| **git refuses in /opt/arkan-monitoring** | `detected dubious ownership` or `Permission denied` | `ls -ld /opt/arkan-monitoring` | Owned by root: owner runs `sudo chown -R ai:ai /opt/arkan-monitoring` (B11) |
| **Docker refuses** | `permission denied while trying to connect to the Docker daemon socket` | `id` | `ai` is not in the `docker` group (B1): owner |
| **Login box keeps coming back** | Browser asks again and again | | Wrong login, or not in `/opt/edge/secrets/hub-users.caddy` or `monitoring-users.caddy`: owner |
| **No "Firmware update" in the menu** | The side menu of `/live/adab/` has no **Firmware update**, or it says `only for the logins listed in ADMIN_USERS` | `grep ADMIN_USERS /opt/arkan-monitoring/server/.env`; `curl -s -u <hub-user> https://arkan-monitoring.duckdns.org/api/v1/admin/me` | Your login name is not in `ADMIN_USERS` (B14), or `.env` was changed without `docker compose up -d` (owner approves). `"user": ""` in the answer: the Caddy file lacks `header_up X-Auth-User` (B21) |
| **Register table stays "Waiting"** | The register page shows *Waiting* for more than 15 minutes | `diff /opt/edge/sites/monitoring.caddy /opt/arkan-monitoring/server/deploy/monitoring.caddy`; `manage.py show-registers LOG-0001` | The Caddy file has no `/api/v1/registers` in `@device` (C5 step 3b); the logger is offline; its firmware is older than 0.4.0 (the page then says *Firmware too old*) |

---

## Part E. Security checklist

Check each line after the install, then every few months.

| # | Rule | How to check | Expected |
|---|---|---|---|
| 1 | The service listens on the **loopback only** | VPS: `ss -ltn \| grep 8800` | `127.0.0.1:8800` only |
| 2 | Port 8800 is closed from the internet | Laptop: `Test-NetConnection arkan-monitoring.duckdns.org -Port 8800` | `TcpTestSucceeded : False` |
| 3 | **Never publish 8644 (Hermes webhook) or 8800.** Docker ports opened as `"8800:8800"` (without `127.0.0.1`) bypass the Linux firewall `ufw`: never change the `ports:` line of the compose file | VPS: `ss -ltn \| grep -E ':(8644\|8800)\b'`; Laptop: `Test-NetConnection arkan-monitoring.duckdns.org -Port 8644` | Only `127.0.0.1` (or the Docker network address, **to verify** with the owner how Hermes binds 8644); `False` from the laptop |
| 4 | Firewall: only SSH (22), HTTP (80), HTTPS (443) open from the internet | Owner: `sudo ufw status verbose` and the Hostinger panel firewall (**to verify** which one is used) | Only 22, 80, 443 allowed |
| 5 | People pages need the Arkan login | B23 checks 1 to 3 | `401` |
| 6 | Logger paths need a valid token | B23 check 4 | JSON `401` |
| 7 | Tokens are stored as **hashes** only | VPS: `grep -c token_sha256 /srv/arkan-monitoring/data/devices.json` | One per logger. No token in clear anywhere on the VPS |
| 8 | No settings file with a token left behind | VPS: `ls -la /srv/arkan-monitoring/data/export/` | No `settings-*.txt` |
| 9 | Secrets only in the password manager | Look at chats, emails, documents, screenshots | No token, no `portal_pass`, no password |
| 10 | Logs hold no secrets | Caddy log filter (B21); the service writes no tokens (C1) | `Authorization` and `Cookie` deleted |
| 11 | The container is locked down | `docker-compose.yml`: `user: "1000:1000"`, `read_only: true`, `mem_limit: 96m`, `cpus: 0.5` | Unchanged |
| 12 | HTTPS everywhere, no indexing | Laptop: `curl.exe -sI https://arkan-monitoring.duckdns.org/live/` | Headers include `strict-transport-security` and `x-robots-tag: noindex, nofollow` (if missing, tell the owner) |
| 13 | SSH by key only | Owner: `sudo sshd -T \| grep -i passwordauthentication` (**to verify** the VPS policy) | `passwordauthentication no` |
| 14 | The other services are untouched | VPS: `docker ps` and `ss -ltn`, compared with B2 | Same as before, plus `arkan-monitoring-ingest` and `127.0.0.1:8800` |
| 15 | Backups exist **off the VPS** (not done yet) | | Today the backups are on the same disk as the data: if the VPS is lost, both are lost. To decide with the owner: a copy elsewhere (for example Google Drive, [../PLAN.md](../PLAN.md) section 5.3). Until then the logger's SD card is the second copy of the records |
| 16 | Firmware update only for named logins | VPS: `grep ADMIN_USERS /opt/arkan-monitoring/server/.env` | Named logins only (not empty if you use it, never `*` without the owner's OK). `FW_GITHUB_TOKEN`, if set, is read-only for this repository only and `.env` is `-rw-------` |
| 17 | Rate limit per device (not done yet) | | Low risk with one logger ([../VPS-SETUP.md](../VPS-SETUP.md) section 11); to add with more sites |

---

## Appendix 1. Command cheat sheet

VPS commands with `docker compose` run in `/opt/arkan-monitoring/server`. `manage.py` below means `docker compose exec ingest python tools/manage.py`.

| Task | Where | Command |
|---|---|---|
| Log in to the VPS | Laptop | `ssh hermes-vps` |
| Leave the VPS | VPS | `exit` |
| Download a file | Laptop | `scp hermes-vps:<path on VPS> .` |
| Upload a file (new name only) | Laptop | `scp .\<file> hermes-vps:<new path on VPS>` |
| Go to the compose folder | VPS | `cd /opt/arkan-monitoring/server` |
| Container status | VPS | `docker compose ps` |
| Health | VPS | `curl -s http://127.0.0.1:8800/health` |
| Service log | VPS | `docker compose logs --tail 100 ingest` |
| Memory of the container | VPS | `docker stats --no-stream arkan-monitoring-ingest` |
| Build and start (owner approves) | VPS | `docker compose up -d --build` |
| Restart, stop, start (owner approves) | VPS | `docker compose restart ingest`, `docker compose stop ingest`, `docker compose start ingest` |
| Current tag | VPS | `git -C /opt/arkan-monitoring describe --tags` |
| Prepare data folder and register | VPS | `manage.py init` |
| Add a site | VPS | `manage.py add-site adab --name "Adab hotel" --contracted-kva 82.5 --rated-a 200 --lat -8.4766 --lon 115.4319` |
| Add a logger (owner) | VPS | `manage.py add-device adab LOG-0001 [--sd-settings /data/export/settings-LOG-0001.txt] [--server <url>]` |
| New token (owner) | VPS | `manage.py rotate-token LOG-0001` |
| Disable or enable a logger | VPS | `manage.py disable-device LOG-0001`, `manage.py enable-device LOG-0001` |
| Status of every logger | VPS | `manage.py list` |
| Alarm log | VPS | `manage.py alarms adab [--lines 50]` |
| Replay the alarm log | VPS | service stopped: `docker compose run --rm ingest python tools/manage.py alarms adab --rebuild` (C6) |
| Daily summary | VPS | `manage.py daily adab` |
| OED files | VPS | `manage.py export-oed adab [--from 2026-11-01] [--to 2026-11-30] [--all] [--out <folder>]` |
| SD card backfill | VPS | service stopped: `docker compose run --rm ingest python tools/manage.py backfill adab LOG-0001 /data/export/sd-LOG-0001` (C9) |
| Publish a firmware | VPS | `manage.py publish-fw /data/firmware-upload-0.4.2.bin [--device LOG-0001]` (or the site page, **Firmware update**) |
| Send a register table | VPS | `manage.py set-registers LOG-0001 /data/export/registers.csv --comment "..."`, `manage.py set-registers LOG-0001 --builtin`, `manage.py show-registers LOG-0001` (or the page `/live/adab/register`) |
| Remote settings | VPS | `manage.py set-config LOG-0001 key=value ...`, `manage.py show-config LOG-0001` |
| Backup by hand | VPS | `/opt/arkan-monitoring/server/deploy/backup.sh` |
| Crontab | VPS | `crontab -l`, `crontab -e` |
| Simulated logger | Laptop | `python .\simulate_logger.py --url https://arkan-monitoring.duckdns.org --token $tok [--backlog-hours 3] [--resend] [--event dip\|hot\|ct\|ota\|sensor] [--live] [--device LOG-0001]` |
| Web check | Laptop | `curl.exe -s -o NUL -w "%{http_code}\n" https://arkan-monitoring.duckdns.org/live/` |
| Port check | Laptop | `Test-NetConnection arkan-monitoring.duckdns.org -Port 8800` |
| DNS check | Laptop | `nslookup arkan-monitoring.duckdns.org` |

`--event` choices of the simulator: `dip` (A26 then A05), `hot` (electrical room hot, A11), `ct` (a CT fitted backwards on L3, A30), `ota` (a remote firmware update, A35), `sensor` (outdoor sensor failed, A14).

## Appendix 2. File and folder cheat sheet

| What | On the VPS | In the container | In the repository |
|---|---|---|---|
| Code | `/opt/arkan-monitoring/` | `/srv/app/` (app and tools only) | the whole repository |
| Compose folder | `/opt/arkan-monitoring/server/` | | `server/` |
| Data folder | `/srv/arkan-monitoring/data/` | `/data/` | |
| Logger registry | `.../data/devices.json` | `/data/devices.json` | |
| Alarm register in use | `.../data/alarm-register.csv` | `/data/alarm-register.csv` | default: `docs/alarms/alarms.csv` |
| Site profile | `.../data/sites/adab/site.json` | `/data/sites/adab/site.json` | |
| 1-minute records | `.../data/sites/adab/LOG-0001/raw/YYYY/MM/YYYY-MM-DD.csv` | `/data/sites/adab/LOG-0001/raw/...` | format: `docs/DATA-FORMAT.md` |
| Alarm log | `.../data/sites/adab/alarms/2026.csv` | `/data/sites/adab/alarms/2026.csv` | columns: `docs/alarms/README.md` |
| Daily summary | `.../data/sites/adab/daily.csv` | `/data/sites/adab/daily.csv` | |
| Logger events | `.../data/sites/adab/LOG-0001/events.jsonl` | | |
| Remote settings | `.../data/sites/adab/LOG-0001/config.json`, `settings-reported.json` | | |
| Firmware for OTA | `.../data/firmware/manifest.json`, `logger-x.y.z.bin` | `/data/firmware/` | |
| Exports and uploads | `.../data/export/` | `/data/export/` | |
| Backups | `/srv/arkan-monitoring/backups/data-<stamp>.tar.gz`, `backup.log` | | script: `server/deploy/backup.sh` |
| Caddy site file | `/opt/edge/sites/monitoring.caddy` | | `server/deploy/monitoring.caddy` |
| Arkan logins | `/opt/edge/secrets/hub-users.caddy` (owner only) | | |
| Logins for this platform only | `/opt/edge/secrets/monitoring-users.caddy` (owner only) | | [../LIVE.md](../LIVE.md#logins) |
| Caddy log of our site | `/var/log/caddy/arkan-monitoring.log` | | |
| Laptop SSH config and keys | | | `C:\Users\<you>\.ssh\config`, `id_ed25519`, `id_ed25519.pub` |

## Appendix 3. Glossary

| Term | Meaning |
|---|---|
| **A01, A02, ...** | Alarm codes of the register ([../alarms/README.md](../alarms/README.md)) |
| **Alarm log** | One line each time an alarm starts, clears, or an event happens: `sites/<site>/alarms/<year>.csv` |
| **Alarm register** | The list of alarms with thresholds and delays: `alarm-register.csv`, opened in Excel |
| **Backfill** | Merging records copied from the SD card into the VPS files |
| **Backlog** | Records kept on the logger and not yet sent (after an outage) |
| **Caddy** | The web server in front of all Arkan services on hermes-vps; reverse proxy and HTTPS |
| **Container, image** | A closed, limited box running one program; the frozen recipe it starts from |
| **cron, crontab** | The Linux scheduler; a user's list of scheduled commands |
| **CSV** | Comma Separated Values: a text table, one line per row, opened by Excel |
| **Detached HEAD** | Git's state when a tag (a fixed version) is checked out instead of a branch: normal on the VPS |
| **docker compose** | The tool that builds and runs the container from `docker-compose.yml` |
| **DuckDNS** | Free names under `.duckdns.org` pointing to an IP address |
| **Hash (SHA-256)** | A one-way fingerprint: the VPS can check a token without storing it |
| **HTTP status code** | The 3-digit answer: 200 OK, 204 OK with nothing to say, 308 redirect, 400 bad request, 401 login or token needed, 403 refused, 404 not found, 413 too big, 502 Caddy cannot reach the service |
| **HTTPS, certificate** | Encrypted web; the certificate proves the server's name. Caddy gets it from Let's Encrypt |
| **Ingest** | Receiving and storing the logger's records (`/api/v1/ingest`) |
| **Live snapshot** | The small set of current values the logger posts every 15 s; shown live and saved 7 days |
| **Loopback (127.0.0.1)** | "This same machine": a port there cannot be reached from the internet |
| **manage.py** | The admin tool of the service (Part C) |
| **OED** | Open Energy Dashboard, the history dashboard, installed in tutorial 3 |
| **OTA** | Over the air: firmware update downloaded by the logger from the VPS |
| **Owner, operator** | The owner has `sudo` and approves live changes; the operator works as `ai` without `sudo` |
| **Port** | A numbered door on a computer (22 SSH, 443 HTTPS, 8800 our service) |
| **portal_pass** | The password of the logger's own setup WiFi `ARKAN-LOG-0001` |
| **Reverse proxy** | A server that receives requests and passes them to the right service inside |
| **scp** | Secure copy between laptop and VPS over SSH |
| **SSH, SSH key** | Encrypted remote command line; the key pair that logs you in without a password |
| **sudo** | Run one command as administrator. Owner only |
| **Swap** | Disk space used as emergency memory |
| **Tag** | A named, fixed version of the code; the VPS runs tags only |
| **Token** | The logger's secret password for the VPS, shown once |
| **uid** | The number of a Linux user. The data folder belongs to uid 1000 |
| **UTC, WITA** | UTC: world time, used in all files. WITA: Central Indonesia Time, UTC+8 (`Asia/Makassar`), used for local days and display |
| **VPS** | Virtual Private Server: the rented computer `hermes-vps` |
