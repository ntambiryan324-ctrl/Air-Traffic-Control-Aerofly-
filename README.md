# Air Traffic Control Aerofly

Android ATC / EFB companion for Aerofly FS Global. The project preserves the original Aerofly telemetry core and places a production-style mobile UI on top of it.

## Aerofly / FSWidgets connection

Aerofly's built-in FSWidgets interface is the primary connection.

- TCP **58585**: the app connects to the simulator and sends the HTTP-style wake-up request before reading the FSWidgets stream.
- UDP **40092**: the companion listens continuously for XGPS/XATT broadcast telemetry.
- The XGPS sentence provides simulator name, longitude, latitude, MSL altitude, true track and groundspeed.
- The XATT sentence provides true heading, pitch and roll.
- The simulator must have **Settings > Miscellaneous > Send flight data to FSWidgets Apps** enabled.
- The TCP target is the IPv4 address of the device running Aerofly. When Aerofly and the companion run on the same Android device, 127.0.0.1 is supported.
- When the simulator and companion are on different devices, use the simulator device's IPv4 address and keep both devices on a network that permits the connection.

These details follow the documented FSWidgets/Aerofly connection procedure. The companion does not depend on the retired FSWidgets Android application.

## Current application features

- Native FSWidgets TCP connection with automatic reconnect.
- UDP XGPS/XATT receiver on port 40092.
- Live aircraft telemetry and connection diagnostics.
- Real interactive moving map using Kivy MapView rather than a fake grid.
- Live aircraft symbol with heading.
- Actual flight-track line.
- Planned-route line from the Flight Plan page.
- Follow-aircraft and recenter controls.
- OpenStreetMap base map.
- Optional OpenAIP aviation tile layer when an OpenAIP API key is supplied.
- ATC communications UI.
- Gemini ATC integration using 'gemini-3.6-flash' by default.
- Persistent, device-local Gemini API-key storage.
- COM1/COM2 frequency management UI and frequency presets.
- Flight-plan entry with major-airport coordinates and custom lat/lon waypoints.
- Top-of-descent calculation.
- Phase, altitude, speed, heading, vertical-speed, pitch and bank monitoring.
- Clearance monitoring and deviation detection.
- AFK copilot monitoring.
- In-app flight alerts.
- Android notification attempt for important alerts when the notification API is available.
- Persistent scratchpad.
- Checklist asset loader for licensed/user-supplied checklist files.
- Connection diagnostics and receiver restart.
- Android microphone permission is included for the voice-input path.

## Map architecture

The previous placeholder grid has been removed from the active UI. The map is now a real tile-based interactive map. MapView supports multitouch pan/zoom, asynchronous tile loading and map markers; it is packaged for Android through Buildozer/Garden.

The aviation chart layer is intentionally optional because OpenAIP requires an API key. The key is entered locally on the device and is not committed to Git.

## Gemini

Default model:

gemini-3.6-flash

The user enters the API key through Settings. It is saved under the application's private data directory and is never stored in source control.

The ATC prompt receives live simulator telemetry so responses can be contextual to altitude, heading, speed, phase, callsign and route.

## Build

GitHub Actions builds a debug APK with Buildozer. Static Python compilation checks run before the Android build.

Checklist assets are intentionally not scraped from copyrighted sources. Add only licensed, public-domain or user-provided checklist assets.
