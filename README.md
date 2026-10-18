# Aerofly ATC

Android companion for Aerofly FS Global (Kivy). Simulation use only, not for real-world navigation.

## Tabs
- **GLOBE** - offline globe that follows the aircraft, route line, zoom, pan, centre.
- **PLAN** - route, flight time, fuel, climb and descent points, vertical profile, live METAR, SimBrief import, GPX to clipboard.
- **ATC** - typed or spoken requests (clearance, taxi, takeoff, approach, landing, direct, altitude, squawk, ATIS, emergency), readback checking, COM frequency panel, optional voice replies. Controller calls are triggered automatically at takeoff, top of descent, approach and landing.
- **TOOLS** - generic checklists, automatic logbook, scratchpad.
- **LINK** - simulator connection and raw-byte capture (to study the real protocol).

## Connect
Two methods, both listed on the LINK tab:
- **A (same as FSWidgets, TCP 58585):** Aerofly > Settings > Miscellaneous > ON 'Send flight data to FSWidgets Apps'. Enter the IPv4 address of the device running Aerofly and tap CONNECT. The app waits for data and sends a single probe request only if the sim stays silent.
- **B (UDP 49002):** Aerofly > Miscellaneous > ON 'Broadcast flight info to IP address', set 'Broadcast IP address' to the device running this app and port to 49002.
If Aerofly runs on the same device, use split-screen or a floating window so Android keeps this app's network alive.

## Files
`main.py` UI and telemetry, `planner_core.py` planning and weather, `atc_engine.py` ATC rules, `extras.py` logbook/checklists/flight events,
`voice.py` Android speech (guarded), `icon.png` app icon, `tests/test_core.py` run with `python tests/test_core.py`.

## Build
GitHub Actions builds an Android ARM64 debug APK with Buildozer, checks Python syntax and the app class, and attaches the APK to a release.
