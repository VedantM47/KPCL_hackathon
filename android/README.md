# KPCL Plant Alert (Android)

Native Android app (Kotlin, no third-party libraries). It keeps a live connection to the plant server
(`GET /live/stream`, Server-Sent Events) in a **foreground service** and, when the plant hits a condition
you should know about, posts a heads-up notification on an alarm-sound channel and plays a loud beep +
vibration. It keeps working with the app closed and the screen off.

## What triggers an alert
| Condition | Level |
|---|---|
| Contract demand breached (kVA above contract) | critical |
| Demand above 85% of contract | high |
| Power factor under 0.90 (penalty band) | medium |
| Anomaly starts on any machine (throttled to one per 90 s) | as scored (mostly critical) |
| Compressed-air leak wasting more than Rs 100 / hour | high |
| Server unreachable for over a minute | high |

"Alert when" in the app filters by level (Everything / High and critical / Critical only).
Beep and notifications are throttled so a burst does not spam the phone.

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
3. Phone on the same Wi-Fi: enter `http://<laptop-ip>:8000` (find it with `ipconfig`) -> **Save & load plants**.
   Away from the laptop's network, run a tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`) and use that https URL.
4. Pick the plant, press **START MONITORING**. **Test alert** checks sound/notifications on the device;
   **Demo: jump to peak day** moves the simulated replay to the plant's highest-demand day so a real alert fires.

**Laptop hotspot (phone connected to the laptop's Wi-Fi hotspot):** the laptop is usually `192.168.137.1`, so use
`http://192.168.137.1:8000`. Run the firewall rule from step 2 in an *administrator* terminal - hotspot networks are
treated as Public and block inbound connections otherwise. Check from the phone's browser: `http://192.168.137.1:8000/plants`
should show JSON.

Android emulator: the default `http://10.0.2.2:8000` reaches the host machine.

## On-call behaviour
Critical alerts act like a page: the **alarm sound loops** (alarm stream, so it is audible even if media is muted) with
repeating vibration until you tap **ACKNOWLEDGE** on the notification or in the app (it also stops after 2 minutes).
The notification stays until acknowledged, wakes the screen and shows over the lock screen. High alerts get one beep.
To let it ring through *Do Not Disturb*: Settings -> Apps -> KPCL Plant Alert -> Notifications -> Plant alerts -> Override Do Not Disturb.

## Notes
- If alerts stop on some phones (Xiaomi, Oppo, Samsung power saving), set the app's battery usage to *Unrestricted*.
- Cleartext http is allowed so a LAN address works; use https for anything exposed to the internet.
- Debug-signed APK: fine for sideloading, not for the Play Store.
