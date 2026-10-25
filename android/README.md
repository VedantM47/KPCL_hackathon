# KPCL Plant Alert (Android)

Native Android app (Kotlin, no third-party libraries). It keeps a live connection to the plant server
(`GET /live/stream`, Server-Sent Events) in a **foreground service**. **Only a critical condition makes the
phone notify and vibrate** — nothing else ever buzzes. It keeps working with the app closed and the screen off.

## What triggers an alert (critical only)
| Condition | Notifies + vibrates? |
|---|---|
| Contract demand breached (kVA above contract) | **yes** — once per breach episode (again only after it has been clear > 1 h simulated) |
| Machine abnormal for 24 hours straight (confirmed fault) | **yes** — once per fault |
| "Simulate critical alert" on the dashboard | **yes** |
| Demand above 85% of contract | no — shown on the live card as "Watch" |
| Power factor < 0.90, anomaly start, air leak | no — visible in the dashboard / developer console |
| Server unreachable for over a minute | no — the app shows "NO DATA" and the silent status notice says so |

Why 24 h for machine faults: in this dataset every anomaly that persists 24 h is a real labelled fault, while
shorter runs are mostly CNC-rule noise (~35% real). Expected pages per simulated year: All plants 7,
Hadapsar 8, Saswad 46, Nashik 15.

## Developer console
Main screen → **Developer console**: *Live data* (every field of the frame being received, its current value,
unit and meaning), *Dataset* (all 20 tables: what a row is, row count, every column explained, paged raw rows)
and *Glossary*. Explanations come from the API (`/dev/dataset`, `/dev/dataset/{table}`, `/dev/glossary`).

## Get the APK
**GitHub Actions** (workflow `.github/workflows/build-apk.yml`): push the repo, open the *Actions* tab, run
*Build Android APK*, download the `KPCL-Plant-Alert-apk` artifact. Tag a commit `v1.0` to also get a Release page.

**Locally** (needs Android SDK + JDK 17+): `cd android && gradle assembleDebug`
-> `app/build/outputs/apk/debug/app-debug.apk`. A pre-built copy is in `android/dist/`.

Install: copy the APK to the phone, open it, allow "install unknown apps". Allow notifications when asked.

## Connect it to the server
The phone must reach the API (the app only talks to your server; there is no cloud).
1. Start the API so it listens on the network:
   `python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`
2. Windows: allow it once - `netsh advfirewall firewall add rule name="KPCL API" dir=in action=allow protocol=TCP localport=8000`
3. Phone on the same Wi-Fi: enter `http://<laptop-ip>:8000` (find it with `ipconfig`) -> **Save & connect**.
   Away from the laptop's network, run a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`) and use that https URL.
4. Pick the plant, press **START MONITORING**. **Test critical alert** checks sound/vibration on the device;
   **Jump to peak day** moves the simulated replay to the plant's highest-demand day so a real alert fires.

**Laptop hotspot (phone connected to the laptop's Wi-Fi hotspot):** the laptop is usually `192.168.137.1`, so use
`http://192.168.137.1:8000`. Run the firewall rule from step 2 in an *administrator* terminal - hotspot networks are
treated as Public and block inbound connections otherwise. Check from the phone's browser: `http://192.168.137.1:8000/plants`
should show JSON.

Android emulator: use `http://10.0.2.2:8000` to reach the host machine (the default is the hotspot address).

## On-call behaviour
Critical alerts act like a page: repeating **alarm-usage vibration** (works in silent mode) plus, if "Alarm sound" is
on, a **looping alarm sound**, until you tap **ACKNOWLEDGE** on the notification or in the app (it also stops after
2 minutes). The notification stays until acknowledged, wakes the screen and shows over the lock screen.
To let it ring through *Do Not Disturb*: Settings -> Apps -> KPCL Plant Alert -> Notifications -> Critical plant alerts -> Override Do Not Disturb.

## Tests
- `cd android && gradle testDebugUnitTest` — JVM tests for frame parsing, the critical-only/once-per-episode rule
  (`AlertGate`) and server-address validation (`app/src/test/.../ModelTest.kt`).
- `python -m pytest tests -q` (project root) — backend: alert severities, stream, control, demo alert, dev console.

## Notes
- If alerts stop on some phones (Xiaomi, Oppo, Samsung power saving), set the app's battery usage to *Unrestricted*.
- Cleartext http is allowed so a LAN address works; use https for anything exposed to the internet.
- Debug-signed APK: fine for sideloading, not for the Play Store.
