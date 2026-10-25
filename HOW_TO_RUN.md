# How to run KPCL (web dashboard + phone app)

Everything here is a **benchmark-calibrated simulation** - synthetic data, assumed tariff and emission factors.

---

## 1. Quick start (the one command)

Open **PowerShell as Administrator** (right-click Start -> Terminal (Admin)) and run:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\imved\OneDrive\Desktop\KPCL\run-demo.ps1"
```

What it does, in order:

1. Frees ports **8000** (API) and **5173** (dashboard) if something is already using them.
2. Adds a Windows firewall rule for port 8000 so the phone can connect (only when run as Administrator).
3. Starts the **API** in its own window ("KPCL API"), listening on all network interfaces.
4. Starts the **dashboard** in its own window ("KPCL Dashboard"). Installs its packages first if missing.
5. Waits until both answer, then prints `=== READY ===` and the address to type into the phone app.

Options:

| Option | Effect |
|---|---|
| `-Breach` | Jumps the live replay to the highest-demand day, so a real contract-breach alert fires after ~90 s |
| `-NoBrowser` | Does not open the dashboard in your browser |

**Timing:** the very first start trains the models (about 1-2 minutes) and saves them to `.cache/`.
Later starts load them in a few seconds. Delete the `.cache` folder to force a retrain.

**To stop everything:** close the two windows ("KPCL API" and "KPCL Dashboard"), or run the script again.

---

## 2. Web dashboard

- Open **http://localhost:5173** (the script opens it for you).
- The **plant switcher** in the top bar (All plants / Hadapsar / Saswad / Nashik) changes every page.
- Pages: Live Monitor, Plant Overview, Compressor Room, Refrigeration, Production, Carbon & ESG, Loss Tracker, Action Center.
- **Click any chart** (or the ⓘ in its corner) for a card explaining what it shows, how to read it, and what the
  current data means. Works on every chart, the What-if simulator and Baseline vs optimized.

### Live Monitor (the demo page) - http://localhost:5173/live
- Shows the plant "live": the server replays a year of data at accelerated speed (1 tick = 15 simulated minutes, one tick per second by default).
- Pause/play, **1x / 4x / 16x** speed, and **Jump to fault...** to move the replay to a planted fault.
- **Simulate critical alert** (red button): instantly raises a critical alert on the dashboard **and on every connected phone** (notification + vibration + alarm). Use it for demonstrations.
- **Facility View** (right of Assets): a 3D view of each plant's rooms and machines, coloured green (running),
  yellow (idle), red pulsing (fault). Switch Hadapsar / Saswad / Nashik with the tabs; click a machine for its
  details; click inside the view first to enable scroll-zoom.

### Reports
- **Plant report PDF** button (Overview, Action Center, Carbon pages): a ~4-page management report for the selected plant, or the whole company, with a sign-off block.
- Carbon page also exports the carbon report as CSV or PDF.

---

## 3. Phone app (Android)

### 3a. Install the APK
Pick one:

- **From this laptop:** copy `android\dist\KPCL-Plant-Alert-debug.apk` to the phone (USB, Drive, WhatsApp to yourself...), open it, allow "install unknown apps". Installing over an older version keeps your settings.
- **From GitHub:** after you push and tag a release (section 5), download
  `https://github.com/VedantM47/KPCL_hackathon/releases/download/<tag>/KPCL-Plant-Alert.apk` on the phone.
  Latest release: `v2.1` — or just open https://github.com/VedantM47/KPCL_hackathon/releases/latest

When asked, **allow notifications**.

### 3b. Connect the phone to the laptop
The phone only talks to your laptop's API, so it must be on the same network.

**Laptop hotspot (what you are using):**
1. Turn on the Windows Mobile Hotspot and connect the phone to it.
2. Start the demo with the script above (as Administrator, so the firewall rule is added).
3. In the app set **Server address** to the hotspot IP, normally `http://192.168.137.1:8000`
   (the script prints every address it finds under `=== READY ===`).
4. Check from the phone's browser: `http://192.168.137.1:8000/plants` should show plant data.

**Same Wi-Fi router instead of hotspot:** use the laptop's Wi-Fi IP (`ipconfig` -> IPv4), e.g. `http://192.168.1.23:8000`.

**Android emulator:** use `http://10.0.2.2:8000` to reach the host machine.

### 3c. Use it
1. Enter the server address -> **Save & connect** (it says how many plants it found).
2. Pick the plant to watch. Leave **Alarm sound** on unless you want vibration only.
3. Press **START MONITORING**. The header badge turns **LIVE** and the card shows kVA, % of contract and status.
4. Press **Test critical alert** to feel the alarm and vibration; **Jump to peak day** makes the replay hit a real breach.
5. **Developer console** shows every live value and every dataset column, explained.

### What triggers an alert — critical only
| Condition | Notification + vibration? |
|---|---|
| Contract demand breached | **yes**, once per breach (again only after it has been clear for over an hour of replay) |
| A machine abnormal for 24 hours straight | **yes**, once per fault |
| **Simulate critical alert** button on the dashboard | **yes** |
| Demand above 85% of contract | no — shown as "Watch" on the live card |
| Power factor, anomaly start, air leak | no — see the dashboard |
| Server unreachable for over a minute | no — the app shows **NO DATA** |

### On-call behaviour
- **Critical:** repeating vibration (works in silent mode) + looping alarm sound (if Alarm sound is on) until you tap **ACKNOWLEDGE** (notification button or the red banner in the app). Also stops after 2 minutes or when you press STOP MONITORING. The notification stays, wakes the screen and shows over the lock screen.
- Nothing else notifies or vibrates.
- To ring through **Do Not Disturb**: Settings -> Apps -> KPCL Plant Alert -> Notifications -> Critical plant alerts -> Override Do Not Disturb.
- If alerts stop with the screen off (Xiaomi / Oppo / Samsung power saving): set the app's battery usage to **Unrestricted**.

---

## 4. Running the pieces by hand (if you don't want the script)

Open three terminals in `C:\Users\imved\OneDrive\Desktop\KPCL`.

**API** (must use `--host 0.0.0.0` for the phone):
```powershell
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```
**Dashboard:**
```powershell
cd web_template
cmd /c "npm install"          # first time only
cmd /c "npm run dev -- --host --port 5173"
```
(Use `cmd /c` for npm - a fresh PowerShell window may block `npm.ps1` under the default execution policy.)

**Firewall rule** (Administrator, once):
```powershell
netsh advfirewall firewall add rule name="KPCL API" dir=in action=allow protocol=TCP localport=8000
```

**Free a stuck port:**
```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen | Select -Expand OwningProcess -Unique | % { Stop-Process -Id $_ -Force }
```

---

## 5. Building a new APK

**On GitHub (no Android tools needed):**
1. Bump `versionCode` / `versionName` in `android/app/build.gradle.kts` and rewrite `RELEASE_NOTES.md`
   (it becomes the release page text).
2. Commit, push, and get it onto `main` (merge the pull request on GitHub).
3. Tag and push the tag:
```powershell
cd C:\Users\imved\OneDrive\Desktop\KPCL
git checkout main
git pull
git tag v2.2
git push origin v2.2
```
The workflow `.github/workflows/build-apk.yml` builds the app. About 3 minutes later the APK is at
`https://github.com/VedantM47/KPCL_hackathon/releases/download/v2.2/KPCL-Plant-Alert.apk`
(also under the repo's **Actions** tab as an artifact). Use a new tag each time. Released so far: v1.0, v2.0, v2.1.

**Locally** (needs Android SDK + JDK 17+):
```powershell
cd android
gradle assembleDebug
```
Output: `android\app\build\outputs\apk\debug\app-debug.apk` (copy it to `android\dist\`).

---

## 6. Rebuilding the data (only if you change the simulation)

The two databases (`kpcl_energy.db`, `kpcl_energy_optimized.db`, ~100 MB each) are **not in git**. After a fresh clone, or after changing `config.yaml` / the generator:

```powershell
python build_db.py --scenario baseline
python build_db.py --scenario optimized
python -m ml.recommendations      # ranked savings per plant (parallel, a few minutes)
python -m ml.whatif               # what-if grid per plant (parallel, a few minutes)
```
Then delete the `.cache` folder so the models retrain on the new data.

---

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| Script says the file does not exist | Use the full path in quotes (section 1), or `cd` into the project folder first |
| Dashboard (5173) not answering | Read the "KPCL Dashboard" window. The script now warns in red if it is down |
| API window shows a Python error | Paste the last lines of that window; nothing else will start without the API |
| Phone says "Cannot reach ..." | Phone not on the hotspot/same network, wrong IP, or the firewall rule is missing - re-run the script as Administrator. Test `http://<ip>:8000/plants` in the phone browser |
| Phone connected but no alerts | Press **Simulate critical alert** on the dashboard, or **Jump to peak day** in the app; check the alert level isn't "Critical only" for a high-level event |
| No sound | Phone media/alarm volume down; Do Not Disturb on (see section 3) |
| Vibration/alarm won't stop | Tap ACKNOWLEDGE; STOP MONITORING also stops it |
| Anything odd after changing data | Delete `.cache\` and restart |

## 8. Ports and files at a glance

| Item | Where |
|---|---|
| API | port 8000 (`api/main.py`, live replay in `api/live.py`) |
| Dashboard | port 5173 (`web_template/`) |
| Launcher | `run-demo.ps1` |
| Phone app source | `android/` (APK in `android/dist/`) |
| Plant report | `api/reports.py` (`/reports/plant?plant=...`) |
| Model cache | `.cache/startup_models.pkl` |
| Project context for developers | `AGENT_CONTEXT.md` |
