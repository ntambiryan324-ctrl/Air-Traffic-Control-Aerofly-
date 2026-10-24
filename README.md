# Aerofly ATC

Android companion for Aerofly FS Global (Kivy). Simulation use only, not for real-world navigation.

## v4.1 stability and charts hand-off
- PLAN and other pages remain mounted in a Kivy ScreenManager, avoiding widget detachment/reparenting on tab changes.
- Button callbacks and page construction are guarded; UI exceptions are written to app-private `ui_errors.log` and surfaced in the UI.
- Planning weather retrieves both METAR and TAF from AviationWeather.gov.
- OPEN CHARTS opens the official Navigraph portal. Licensed chart content is not copied or bundled.

## Tabs
- **GLOBE** - offline globe that follows the aircraft, route line, zoom, pan, centre.
- **PLAN** - route, flight time, fuel, climb and descent points, vertical profile, live METAR, SimBrief import, GPX to clipboard.
- **ATC** - typed or spoken requests (clearance, taxi, takeoff, approach, landing, direct, altitude, squawk, ATIS, emergency), readback checking, COM frequency panel, optional voice replies. Controller calls are triggered automatically at takeoff, top of descent, approach and landing.
- **TOOLS** - generic checklists, automatic logbook, scratchpad.
- **LINK** - simulator connection and raw-byte capture (to study the real protocol).

## Connect
Two methods, both listed on the LINK tab:
- **A (FSWidgets-compatible TCP 58585):** In Aerofly FS Global, enable Settings > Miscellaneous > 'Send flight data to FSWidgets Apps'. Enter the simulator device's IPv4 address and tap CONNECT. The client sends the HTTP-like stream request used by the mobile endpoint, retries connections, and parses line-framed or concatenated XGPS/XATT records.
- **B (UDP):** If your simulator exposes broadcast telemetry, set its destination IP to this device and use UDP port 49002 (the app also listens on 40092).
If Aerofly runs on the same device, use split-screen or a floating window so Android keeps this app's network alive.

## Files
`main.py` UI/map, `telemetry.py` simulator networking and XGPS/XATT parsing, `planner_core.py` planning and weather, `atc_engine.py` ATC rules, `extras.py` logbook/checklists/flight events,
`voice.py` Android speech (guarded), `icon.png` app icon, `tests/test_core.py` run with `python tests/test_core.py`.

## Build
GitHub Actions builds an Android ARM64 debug APK with Buildozer, checks Python syntax and the app class, and attaches the APK to a release.
