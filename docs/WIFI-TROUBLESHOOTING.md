# WiFi troubleshooting: the logger does not connect on site

For: the technician on site, with the hotel's IT or engineering contact on the phone. Logger `LOG-0001`, site `adab`, platform `https://arkan-monitoring.duckdns.org`.
Firmware: **0.4.1 and 0.5.1** (differences are marked). Written 11 November 2026 from the firmware source ([`firmware/src/net.cpp`](../firmware/src/net.cpp), [`firmware/src/portal.cpp`](../firmware/src/portal.cpp)) and the WiFi library it is built with (Arduino-ESP32 core 2.0.17).

**The situation:** the hotel WiFi name and password were entered, everyone believes they are correct, but the logger does not come online. The live page `/live/adab/` stays at "No data", and `status` (or the portal's status box) shows `WiFi: down for n s`.

**Never** write the WiFi password or the device token in a report, photo, chat or ticket. Clear the serial monitor before you show your screen to anyone.

---

## Contents

1. [The ten usual causes](#1-the-ten-usual-causes)
2. [Before you start](#2-before-you-start)
3. [How the logger connects, and how long it waits](#3-how-the-logger-connects-and-how-long-it-waits)
4. [Find which stage fails (5 minutes)](#4-find-which-stage-fails-5-minutes)
5. [Check what is really stored](#5-check-what-is-really-stored)
6. [Stage 1: the logger does not find the network](#6-stage-1-the-logger-does-not-find-the-network)
7. [Stage 2: the network is found but refuses the logger](#7-stage-2-the-network-is-found-but-refuses-the-logger)
8. [Stage 3: joined, but no IP address](#8-stage-3-joined-but-no-ip-address)
9. [Stage 4: WiFi up, but no data on the live page](#9-stage-4-wifi-up-but-no-data-on-the-live-page)
10. [Power: the logger restarts when it uses WiFi](#10-power-the-logger-restarts-when-it-uses-wifi)
11. [The phone hotspot test: the logger or the network?](#11-the-phone-hotspot-test-the-logger-or-the-network)
12. [Message for the hotel IT](#12-message-for-the-hotel-it)
13. [Record and escalate](#13-record-and-escalate)
14. [Known limits of the firmware (0.5.1 and older)](#14-known-limits-of-the-firmware-051-and-older)

---

## 1. The ten usual causes

The most likely first. Section 4 tells you which of them applies in a few minutes.

| # | Cause | Quick check | Section |
|---|---|---|---|
| 1 | The name stored is not **exactly** the network's name (a capital letter, a space, `-` instead of `_`; the phone capitalised the first letter) | `show` against the `wifi` scan, character by character | [5](#5-check-what-is-really-stored) |
| 2 | The password stored is not the one you think (a typo; the old office password kept because the portal's password field was left empty; typed in `wifi_pass2` instead of `wifi_pass`; filled in by the phone's autofill) | Type it again on the console and read the echoed line | [5](#5-check-what-is-really-stored) |
| 3 | The network is **5 GHz only** (the ESP32-S3 has no 5 GHz radio) | Not in the logger's `wifi` list, the phone sees it at 5 GHz | [6](#6-stage-1-the-logger-does-not-find-the-network) |
| 4 | The signal is too weak where the board is (panel steel, lid closed) | `wifi`: worse than -75 dBm | [7.3](#73-signal-strength-at-the-box) |
| 5 | The hotel network admits only **registered devices** (MAC address filter, device approval) | The phone joins, the logger is refused (status 4, 5, 6 or 0) | [7.5](#75-mac-address-filter-or-device-approval) |
| 6 | The network has a **login page** (guest network: room number, name) | WiFi up, uploads fail with `-1` | [9](#9-stage-4-wifi-up-but-no-data-on-the-live-page) |
| 7 | A **security type** the logger cannot use: Enterprise (with a username), WPA3 only, WEP or old WPA | Ask IT | [7.2](#72-security-type) |
| 8 | **Several access points** with the same name: the logger tried a far one | The name appears several times in `wifi` | [7.4](#74-several-access-points-with-the-same-name) |
| 9 | The hotel **firewall** blocks the platform (HTTPS, "dynamic DNS" filter, SSL inspection) | The phone on the hotel network cannot open the live page | [9](#9-stage-4-wifi-up-but-no-data-on-the-live-page) |
| 10 | The **power supply** sags when the WiFi transmits (brown-out restarts) | `status`: `boot brownout`, uptime always short | [10](#10-power-the-logger-restarts-when-it-uses-wifi) |

---

## 2. Before you start

Bring:
- the laptop with VS Code, PlatformIO and this repository, and a USB-C **data** cable (packing list: [tutorial 1, A10](tutorials/1-LOGGER-ON-SITE.md#a10-final-checklist-before-the-site));
- your phone with the password manager: the hotel WiFi password, and `LOG-0001`'s setup WiFi password (`portal_pass`);
- a WiFi analyser app on the phone if you have one (it shows each network's band, channel and dBm);
- the phone number of the hotel's IT or engineering contact. If they can open the access point's or router's admin page while you test, most of this page goes much faster.

**The board has one USB-C port.** Using the console means unplugging the adapter's cable and plugging in the laptop's: a short power cut (an **A02** line in the alarm log, expected during the work). So first read what you can from the phone ([4.1](#41-from-the-phone-no-power-swap)), then swap to the laptop.

---

## 3. How the logger connects, and how long it waits

A connection goes through four stages. Each stage fails in its own way, so the first job is to find which stage fails.

```
  1. FIND               2. JOIN                  3. ADDRESS               4. REACH THE PLATFORM
  scan 2.4 GHz     -->  name + password     -->  DHCP gives an IP    -->  internet, DNS, HTTPS (443),
  for the name          security WPA2            address                  token --> data on the live page
```

- The log line `WiFi connected to "<name>" ip=... rssi=... ch=...` appears only when stage 3 is done. Data on the live page needs stage 4 too.
- One try lasts **20 s** per network. Firmware **0.5.1** first scans (about 2 s) and tries only the configured network(s) it saw; if it saw none of them, it tries both anyway. Firmware **0.4.1** does not scan: it tries `wifi_ssid` and `wifi_ssid2` in turn, one per try.
- After a failed try it waits **10, 20, 40, 80, 160 s, then 5 minutes** between tries. While the setup portal is open it waits **at least 2 minutes**.
- So **after any fix, restart the logger** (`reboot` on the console, "Save and restart" in the portal, or unplug and replug the power). Otherwise you may wait up to 5 minutes for the next try and think the fix did not work.
- Every 30 minutes offline it restarts its WiFi driver; after 6 hours offline it restarts itself (boot reason `sw:offline`). These are consequences of the problem, not causes.
- Nothing is lost while it is offline: the records stay on the SD card and are sent once it is online (as long as the clock is valid).

---

## 4. Find which stage fails (5 minutes)

### 4.1 From the phone, no power swap

1. **Look at your phone's WiFi list before you press anything.** If **`ARKAN-LOG-0001`** is already there, the logger most likely has **no WiFi network stored at all**: the setup WiFi stays on by itself only in that case (or for 15 minutes after someone opened it). The settings were never saved: enter them again ([tutorial 1, B8](tutorials/1-LOGGER-ON-SITE.md#b8-putting-the-logger-on-the-hotel-wifi-setup-portal)) and read [section 5](#5-check-what-is-really-stored) first.
2. **Open the portal:** hold BOOT 3 to 4 s through the lid hole, join `ARKAN-LOG-0001` with the setup password, open `http://192.168.4.1` (details: [B8](tutorials/1-LOGGER-ON-SITE.md#b8-putting-the-logger-on-the-hotel-wifi-setup-portal) steps 1 to 3).
3. **Read the grey status box on the first page load.** The first load usually still shows what the logger saw at its last search, before the portal opened. Once it tries again with the portal open, the line changes to `not scanned (setup portal open)`, because it does not search while the portal is open.

   | The status box shows | Means | Go to |
   |---|---|---|
   | `WiFi: down for n s, in range at the last scan: "<hotel network>"` (0.5.1) | The logger sees the network but cannot join or get an address: stage 2 or 3 | [5](#5-check-what-is-really-stored), then [7](#7-stage-2-the-network-is-found-but-refuses-the-logger) |
   | `... in range at the last scan: none of the configured networks (n other networks seen)` (0.5.1) | The logger sees **no** network with the stored name: stage 1 | [5](#5-check-what-is-really-stored), then [6](#6-stage-1-the-logger-does-not-find-the-network) |
   | `... in range at the last scan: not scanned yet` | No try has finished since the restart | Wait 1 minute, reload |
   | `WiFi: down for n s` and nothing after it | Firmware 0.4.1: it does not say what it saw | Read the "WiFi networks seen" line (next step), then use the console ([4.2](#42-from-the-laptop-serial-console)) |
   | `WiFi: up, <name> <ip> rssi -nn dBm` | Stages 1 to 3 are fine | [9](#9-stage-4-wifi-up-but-no-data-on-the-live-page) |
   | First line `up n s, boot: brownout`, or an uptime that is always short | The board keeps restarting | [10](#10-power-the-logger-restarts-when-it-uses-wifi) |
   | `Time (UTC): NOT SET` | Nothing is recorded until the clock is set | [9](#9-stage-4-wifi-up-but-no-data-on-the-live-page) (first row) |

4. **Read the line "WiFi networks seen"**: is the hotel network there, spelled how, and at how many dBm? If it says "scanning, reload in a few seconds", reload. Only the first **12** networks are listed: in a hotel with many networks yours may be cut off, so use the console's `wifi` ([4.2](#42-from-the-laptop-serial-console)), which lists them all.
5. **Close the portal** with the grey button "Close the setup WiFi" when you are done. While it is open the logger tries only every 2 minutes, and each try can drop your phone off `ARKAN-LOG-0001` for a moment.

### 4.2 From the laptop (serial console)

Swap the power to the laptop and open the monitor in the `firmware` folder:
```powershell
pio device monitor
```
Then type each command and press Enter (what you type is not shown until you press Enter).

**a. The state now:**
```
status
```
Read the first line (`up n s, boot <reason>`), `Time:`, `WiFi:` (same meanings as the table in 4.1) and `Uploads:`.

**b. The event log** (use the current month in **UTC**; if the clock is not set, the file is `/log/no-clock.log`):
```
tail /log/2026-11.log 40
```
Look for:
- `WiFi: connection failed (attempt n, status s, in range: ...), next try in n s` (0.4.1: without `in range`). It is written at the 1st failed try and then every 10th. **The status number `s` tells you the stage: see [4.3](#43-what-the-status-number-means).**
- `WiFi connected to "<name>" ip=... rssi=... ch=...` followed later by `WiFi lost (status n)`: it joins, then drops: [7.3](#73-signal-strength-at-the-box) and [7.4](#74-several-access-points-with-the-same-name).
- `BOOT fw=... reason=brownout` again and again: [10](#10-power-the-logger-restarts-when-it-uses-wifi).
- `Setting wifi_ssid changed from the setup portal` (or `from the console`): when the settings were really changed.

**c. What the logger hears:**
```
wifi
```
One line per network: `  <name>  ch <channel>  <rssi> dBm`. Run it 3 to 5 times (if it prints nothing, the logger was in the middle of a try: run it again). Note for the hotel network: is it there, spelled how, how strong, on which channel(s), and **how many times** it appears.

**d. What is stored:**
```
show
```
`wifi_ssid` and `wifi_ssid2` exactly as stored. Passwords show as `******`.

**e. Watch one try live.** Type `reboot`. With the native USB build the port drops at the restart: run `pio device monitor` again. Then **do not type anything** for one minute (a `wifi` scan during a try can disturb it). The logger prints, at each try:
```
WiFi: connecting to "<name>"
```
The quotes show exactly what is stored, so a wrong capital or an extra character is visible. Then, within 20 s, either `WiFi connected to "<name>" ip=... rssi=... ch=...`, or nothing until `WiFi: connection failed (attempt 1, status s, ...)`.

### 4.3 What the status number means

The number `s` in `WiFi: connection failed (..., status s, ...)` and `WiFi lost (status s)` is the WiFi library's state at the end of the try. When two networks are tried in one round, it is the state of the **last** one tried.

| Status | Means | Stage | Go to |
|---|---|---|---|
| `1` | No access point with that name was found during the try: the name is wrong, the network is out of range or 5 GHz only, **or** its security is older than WPA2 (WEP, WPA with TKIP): the logger skips such networks as if they did not exist | 1 | [6](#6-stage-1-the-logger-does-not-find-the-network) |
| `4`, `5` or `6` | The access point was found, but the login failed or was cut. Most often the **password**; also a security type the logger cannot use, a MAC address filter, an access point that refuses new devices, or a signal too weak to finish the login | 2 | [5](#5-check-what-is-really-stored), then [7](#7-stage-2-the-network-is-found-but-refuses-the-logger) |
| `0` | Joined (the password was accepted), but no IP address came within 20 s | 3 | [8](#8-stage-3-joined-but-no-ip-address) |
| `255` | The WiFi driver was off for a moment (its 30-minute restart) | | Ignore it, read the next line |

---

## 5. Check what is really stored

"The password is correct" is the most common wrong assumption. Check these in order, even if someone is sure.

1. **The name, character by character.** Compare `show` (or the `WiFi: connecting to "..."` line) with the network as listed by `wifi`. Capitals, spaces, `-` and `_`, `0` and `O`, `l` and `I` all count.
   **Phone trap:** in the portal, `wifi_ssid` is an ordinary text field. Phones often **capitalise its first letter** by themselves and may **autocorrect** a word. After "Save and restart", open the portal again and read the `wifi_ssid` field as stored, or check with `show` on the console.
2. **The password.** It is never shown again (`******`), so the only sure way is to type it again. On the console the line you typed is printed after Enter, so you can read exactly what was stored:
   ```
   set wifi_pass <hotel WiFi password>
   ```
   Expected: `> set wifi_pass ...` (your line) and `wifi_pass set. Type 'reboot' to apply.` Read the echoed line carefully, then:
   ```
   reboot
   ```
   Clear the monitor window afterwards (the password is on screen); never take a screenshot of it.
   The traps:
   - in the portal, an **empty password field keeps the old value**. If only the name was changed there, the old password (often the office one) is still stored;
   - each name goes with its own password: `wifi_pass` with `wifi_ssid`, `wifi_pass2` with `wifi_ssid2`. The hotel name in `wifi_ssid2` with its password in `wifi_pass` cannot work;
   - the phone's browser or password manager may **fill a password field by itself** (`wifi_pass`, `dev_token` or `portal_pass`) with a saved password. Before you tap "Save and restart", check that only the fields you meant to fill have something in them. A wrong `dev_token` does not stop the WiFi but stops the uploads;
   - a space at the **start or end** of a name or password is removed by the logger (portal, console and SD file alike). A network whose name or password starts or ends with a space cannot work: ask IT to change it.
3. **Is the password really correct?** Prove it with a phone, typed by hand: in the phone's WiFi settings **forget** the hotel network, then join it again typing the password from the password manager (not a saved one).
   - The phone is refused: the password is wrong or was changed. Ask the hotel (or the owner) for the current one.
   - The phone joins: the password is right. Continue with the next sections.
4. **Were the settings applied?** Settings take effect only after a restart: after `set ...` you must type `reboot`. With firmware 0.5.1 and two networks, the boot log shows `WiFi: networks "<first>" and "<second>": joins the one in range, stays on it until the link drops`.
5. **Do not type `factory`.** It erases every setting, including the device token, which cannot be recovered on site.

---

## 6. Stage 1: the logger does not find the network

Signs: `status 1` in the log, or `in range at the last scan: none of the configured networks` (0.5.1).

1. **Is the hotel network in the logger's `wifi` list?**
   - **Yes:** then the name stored differs from it ([section 5](#5-check-what-is-really-stored) step 1), or its security is older than WPA2 ([7.2](#72-security-type)).
   - **No, but the phone sees it:** continue below.
2. **5 GHz only.** On the phone, open the network's details: a frequency of **5 GHz**, or a channel of **36 or more**, means 5 GHz. Hotels often use one name for both bands; if the 2.4 GHz radio is off, or that name is only on 5 GHz, the logger never sees it.
   **Fix:** ask IT to put that name on 2.4 GHz too, or to give a 2.4 GHz network for devices (often called `...-2G` or `...-IoT`).
3. **Hidden network** (the name is not broadcast: on the phone it had to be added by hand). Firmware 0.5.1 then reports `none of the configured networks` because a scan cannot see a hidden name, but it still tries the stored names, so a hidden network can work. If it does not: ask IT to make it visible.
4. **Too weak.** Not in the list, or listed at -85 dBm or worse: [7.3](#73-signal-strength-at-the-box).
5. **"WiFi 6 only" (802.11ax only) on 2.4 GHz.** The logger speaks 802.11 b/g/n. Ask IT to allow b/g/n on the 2.4 GHz radio.
6. **Network switched off at times.** Some access points run on a schedule, or were being restarted while you tested: ask IT.

---

## 7. Stage 2: the network is found but refuses the logger

Signs: `status 4`, `5` or `6` in the log while the network is in the `wifi` list.

### 7.1 Password

Still the first suspect: [section 5](#5-check-what-is-really-stored), steps 2 and 3.

### 7.2 Security type

Ask IT, or read it on the phone: Android shows "Security" in the network's details; an iPhone shows **"Weak Security"** under the name when the network uses WEP or WPA with TKIP.

| Security on the access point | Logger |
|---|---|
| WPA2-Personal (WPA2-PSK, AES) | **Works.** This is what we use |
| WPA2/WPA3-Personal mixed ("transition mode") | Should work |
| WPA3-Personal only (SAE) | **Not tested** on our board. If it fails, ask IT for WPA2/WPA3 mixed |
| WPA2 or WPA3-**Enterprise** (802.1X, RADIUS: each person has a **username** and a password) | **Not supported:** the logger has no username setting. Ask IT for a WPA2-Personal network for devices |
| WEP, or WPA with TKIP only | **Refused** by the logger (minimum WPA2). Shows as status 1 |
| Open with a login page (guest network: room number, name, voucher) | Joins, then cannot pass the login page: no data. See [9](#9-stage-4-wifi-up-but-no-data-on-the-live-page) |
| Open, no login page | Works (leave `wifi_pass` empty). Not recommended |

### 7.3 Signal strength at the box

Measure where the board really is: in the box, **lid closed**, box mounted. On the console run `wifi` 5 to 10 times and take the mean of the hotel network's dBm. (The live page's Logger card, and the `rssi` column of the day file, show it once the logger is online.)

| Mean RSSI | Means |
|---|---|
| -50 to -70 dBm | Good. -70 dBm is our minimum |
| -70 to -80 dBm | Joins slowly, may fail or drop. Improve it |
| Worse than -80 dBm | Unreliable: the login often fails (status 5 or 6). Once online, alarm **A17** Weak WiFi |

Every 3 dB less is half the power, so a few dB matter. To improve it:
- the board's **antenna end up**, with no cable, wire or metal over it. The module has a PCB antenna and no external antenna connector;
- the box **30 cm or more from the panel steel**; higher, or nearer the door of the panel room ([tutorial 1, B1](tutorials/1-LOGGER-ON-SITE.md#b1-arrival-and-site-survey) step 5);
- ask the hotel whether an access point of the same network is nearer, or whether one can be added (2.4 GHz);
- a 4G router is not in the plan ([`QUESTIONS.md`](QUESTIONS.md) Q9): changing that is for the supervisor and the owner.

### 7.4 Several access points with the same name

Hotels often have several access points broadcasting the same network name. The logger (firmware 0.5.1 and older) joins the **first** access point with that name it finds while it searches the channels in order, **not the strongest one**. If a far access point is on a lower channel than the near one, the logger may try the far one at a weak signal and fail or drop, while your phone, which picks the strongest, works fine next to it.

Signs:
- `wifi` lists the hotel network **several times**, on different channels, with different dBm;
- the log shows failures with status 5 or 6 although the strongest entry in `wifi` is better than -70 dBm; or `WiFi connected ... rssi=-8n ch=<n>` where `ch` is not the channel of the strongest entry.

What to do:
- ask IT to tie the logger to the access point nearest the panel (many WiFi controllers can lock one device to one access point), or to give it a network name that **only that access point** broadcasts;
- tell the supervisor: a firmware change (search all channels, join the strongest) removes this trap ([section 14](#14-known-limits-of-the-firmware-051-and-older)).

### 7.5 MAC address filter or device approval

Many hotel staff networks admit only registered devices. Typical sign: the phone joins with the same password, the logger is refused (status 4, 5 or 6) or joins without getting an address (status 0).

Ask IT: "Is there a MAC address filter, a device registration or an approval step on this network?" If yes, give them the logger's **WiFi MAC address**.

How to find the MAC address:
- it is printed **every time the firmware is flashed**: in the output of `pio run -t upload`, the line `MAC: xx:xx:xx:xx:xx:xx` is the WiFi address. Flashing the same firmware again on site is harmless (the settings stay in NVS): see [tutorial 1, A4.6](tutorials/1-LOGGER-ON-SITE.md#a46-flash-upload), with the build written in the record sheet (`logger` or `logger-uart`);
- in a router's or controller's list of devices, the logger usually appears as **`esp32s3-XXYYZZ`**, where `XXYYZZ` is the end of its MAC address (it may also appear as `LOG-0001` after the setup portal was used), with the maker **Espressif**. At the office, the office router's list gives you the full address;
- write it in the bench record and the as-built record: it is not a secret.

### 7.6 Other refusals, and the access point's log

- **Band steering** ("prefer 5 GHz"): with one name on both bands, some access points refuse a device's first tries on 2.4 GHz to push it to 5 GHz. The logger cannot move to 5 GHz. Ask IT to switch band steering off for this network (or for the logger's MAC address), or to give a 2.4 GHz-only name.
- **Client limit** reached on the access point (too many devices): IT sees it in the access point's status.
- **Ask IT to read the access point's or controller's event log** while the logger tries (it tries 10, 20, 40 s... after a restart: [section 3](#3-how-the-logger-connects-and-how-long-it-waits)). Look for `esp32s3-...`, `LOG-0001`, the MAC address or the maker Espressif. The log usually gives the exact reason: wrong key, MAC address denied, authentication timeout, association refused. The logger itself does not record that reason ([section 14](#14-known-limits-of-the-firmware-051-and-older)), so this is the fastest way when IT has access.

---

## 8. Stage 3: joined, but no IP address

Signs: `status 0` in the log. The password was accepted, but the network gave no address within 20 s.

- **DHCP pool full, or DHCP off** on that network: IT checks.
- **Device waiting for approval:** some systems let a new device join but give it no address until an administrator approves it. IT approves the logger ([7.5](#75-mac-address-filter-or-device-approval)).
- **No fixed address possible:** the logger has no setting for a fixed IP address. If the network has no DHCP, ask IT for a DHCP reservation for its MAC address instead.
- A very weak signal can also do this: [7.3](#73-signal-strength-at-the-box).

---

## 9. Stage 4: WiFi up, but no data on the live page

`status` shows `WiFi: up, <name> <ip> rssi -nn dBm`, but the live page stays at "No data". Read the other lines of `status`:

| `status` shows | Means | What to do |
|---|---|---|
| `Time: NOT SET` and `Last sample: (clock not set, nothing recorded)` | No valid clock: the logger records nothing. The internet time service (NTP, UDP port 123) may be blocked, and the RTC has lost its time | Set it by hand in **UTC** (not WITA): `time set 2026-11-12T03:15:00`. Ask IT to allow NTP to `pool.ntp.org` and `time.google.com`. If the time is lost at every power cut, replace the CR1220 cell |
| `Uploads: ok 0, failed n, last error -1` | The logger cannot open the HTTPS connection to the platform: login page, firewall, DNS filter, SSL inspection, or the platform is down | The phone tests below |
| `last error -11` | Connected, but the answer did not come in time: slow or weak link | [7.3](#73-signal-strength-at-the-box); type `upload` to try again; if it stays, ask the operator |
| `last error 401 ...` or `403 ...`, or `Server: ... (NO TOKEN)` | Token refused or missing | [Tutorial 1, C6](tutorials/1-LOGGER-ON-SITE.md#c6-troubleshooting), "Token refused" |
| `last error 5xx ...` (500 to 599) | The platform answered with an error | Ask the operator |
| `Uploads: ok n` growing | The data goes up | If the live page still says "No data", see [C6](tutorials/1-LOGGER-ON-SITE.md#c6-troubleshooting), "Live page No data" |

**The phone tests for `-1`.** Your phone tells you what the hotel network lets through.

1. Phone on the **hotel network**, mobile data **off**. Open `http://neverssl.com` (http, not https).
   If a **login page** appears instead (room number, name, "accept"), the network has a captive portal. The logger cannot pass it. Use the staff network, or ask IT to let the logger's MAC address through without the login page.
2. Same phone, same network: open `https://arkan-monitoring.duckdns.org/live/adab/`.
   - **It loads:** the network lets the platform through, at least for the phone. If the logger still gets `-1`, ask IT whether devices are filtered differently from phones (by MAC address or by device type).
   - **It fails here but loads on mobile data:** the hotel network blocks it. Ask IT to allow outbound HTTPS (TCP port 443) to `arkan-monitoring.duckdns.org`. Some web filters block every "dynamic DNS" name such as `duckdns.org` as a category: ask for an exception for this name.
   - **The browser warns about the certificate on the hotel network only:** the firewall inspects HTTPS traffic (SSL inspection) and replaces the certificate. The logger refuses such a certificate on purpose (`tls_verify` = 1). Ask IT to exempt the logger (its MAC or IP address) from SSL inspection. **Do not set `tls_verify` to 0**: only the owner decides that.
   - **It fails on mobile data too:** the platform is down. Ask the operator to check the service.
3. After any change on the network side, type `upload` on the console, then `status` a few seconds later: `Uploads: ok 1` or more.

---

## 10. Power: the logger restarts when it uses WiFi

When the WiFi transmits, the board draws short current peaks. With a weak adapter, a long or thin USB cable, or a loose plug, the voltage dips and the chip restarts (**brown-out**). It then looks like "the WiFi never connects".

Signs:
- `status`: first line `up n s, boot brownout` with a short uptime, or the portal's first line `boot: brownout`;
- the event log has `BOOT fw=... reason=brownout` again and again;
- the day file's `boot` column shows `brownout`; the alarm log shows **A02** Power interruption without a real power cut;
- typical: it works on the laptop's USB but not on the adapter, or the opposite.

Fix: the branded **5 V / 2 A** adapter, a short good USB-C cable, a firm plug. **USB-C only, never the DC jack.**

Not causes: `sw:offline` every 6 hours (a consequence of being offline) and `sw:daily` at 03:05 WITA (planned).

---

## 11. The phone hotspot test: the logger or the network?

If you are stuck, prove whether the logger itself works. It takes 5 minutes.

1. Make a **hotspot** on a phone that has mobile data:
   - **2.4 GHz**: on an iPhone, Personal Hotspot with **Maximize Compatibility** on; on Android, choose the 2.4 GHz band in the hotspot settings;
   - WPA2, a simple name without spaces, a password of 8 characters or more.
2. On the console, note the current `wifi_ssid2` (`show`), then:
   ```
   set wifi_ssid2 <hotspot name>
   set wifi_pass2 <hotspot password>
   reboot
   ```
3. Expected within 1 to 2 minutes (with 0.5.1 it may first try the hotel network for 20 s; 0.4.1 alternates): `WiFi connected to "<hotspot name>" ...`, then within 2 minutes `Uploads: ok 1` or more in `status`, and "Live" on the live page.
   - **It works:** the logger, its token and the platform are fine. **The problem is the hotel network**: sections 6 to 9, with IT.
   - **It fails too:** the problem is the logger (settings, power, antenna) or the platform. Tell the supervisor.
4. **Undo it:** put back what was there before (`unset wifi_ssid2` and `unset wifi_pass2`, or the previous values), then `reboot`. Do not leave your hotspot stored: the logger would join it whenever your phone is near.

---

## 12. Message for the hotel IT

Copy, fill in the MAC address, and send it (no password and no token in it):

```
Our energy logger LOG-0001 (a small WiFi device with no screen) must join your staff network.
It needs:
- a 2.4 GHz network (it has no 5 GHz radio), with 802.11 b/g/n allowed
- WPA2-Personal, or WPA2/WPA3 mixed. It cannot use a username (no Enterprise / 802.1X)
  and cannot pass a login page
- DHCP (it cannot use a fixed address)
- its WiFi MAC address is __:__:__:__:__:__ (it may show as "esp32s3-......" or "LOG-0001",
  maker Espressif). If you filter or approve devices, please allow it
- outbound HTTPS (TCP 443) to arkan-monitoring.duckdns.org, and NTP (UDP 123) to pool.ntp.org
  and time.google.com
- no SSL inspection for this device
- if several access points carry the network: please tie it to the access point nearest the
  main electrical panel, or give it a network name only that access point carries
Could you also look at your access point or controller log for this device while it tries to
connect, and tell us the reason it is refused?
```

---

## 13. Record and escalate

When you call the supervisor, and before you leave the site, write down (**never** the password or the token):
- firmware version, build (`logger` or `logger-uart`), WiFi MAC address;
- the `status` output (first line, `Time`, `WiFi`, `Uploads`);
- the log lines `WiFi: connection failed (...)`, `WiFi connected ...`, `WiFi lost ...`, `BOOT ...` from `tail /log/<YYYY-MM>.log 40`;
- the `wifi` scan: the hotel network's name as listed, its channel(s), dBm, and how many times it appears;
- band and security type (from IT or the phone), and whether there is a MAC address filter or a login page;
- what you tried, in order, with the result of each, and the result of the hotspot test ([section 11](#11-the-phone-hotspot-test-the-logger-or-the-network)).

Put it in the Lab 7 record and the "open points" of the as-built record ([`install/README.md` section 13](install/README.md#13-as-built-record-template)).

---

## 14. Known limits of the firmware (0.5.1 and older)

These make the diagnosis harder. A later firmware could remove them; until then, use the workarounds above.

- The logger does not record the **reason** the network gave for a refusal (wrong key, access point not found, authentication timeout...), only the status number of [4.3](#43-what-the-status-number-means). The access point's own log ([7.6](#76-other-refusals-and-the-access-points-log)) is more precise.
- It joins the **first** access point it finds with the right name, not the strongest ([7.4](#74-several-access-points-with-the-same-name)).
- The portal's text fields leave the phone's auto-capitalisation and autocorrect on ([section 5](#5-check-what-is-really-stored) step 1).
- The WiFi MAC address is not shown by `status` or by the portal ([7.5](#75-mac-address-filter-or-device-approval)).
- The host name `LOG-0001` is set too late to reach the network after a normal start: routers usually list the logger as `esp32s3-XXYYZZ` ([7.5](#75-mac-address-filter-or-device-approval)).

---

See also: [tutorial 1, B8](tutorials/1-LOGGER-ON-SITE.md#b8-putting-the-logger-on-the-hotel-wifi-setup-portal) (the setup portal) and [C6](tutorials/1-LOGGER-ON-SITE.md#c6-troubleshooting) (all other symptoms); every setting: [`FIRMWARE.md`](FIRMWARE.md#3-all-settings); the RSSI survey: [`install/README.md` Lab 4](install/README.md#lab-4-network-and-upload).
