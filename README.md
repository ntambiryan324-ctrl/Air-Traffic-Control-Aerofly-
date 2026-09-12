# Aerofly Flight Companion

A standalone Android companion for Aerofly FS Global.

## Build
GitHub Actions builds a debug APK with Buildozer. The project intentionally keeps the Android build surface small and deterministic.

## Telemetry
The app listens for JSON UDP telemetry on port 58585. Example payload:

{"callsign":"UAL123","lat":37.6,"lon":-122.4,"altitude":12000,"speed":250,"heading":180,"vertical_speed":-800,"on_ground":false}

## Included foundation
- Local telemetry receiver
- Copilot clearance/state monitor
- AFK communications state
- EFB flight-follow display
- Aircraft checklist selector
- TOD calculation
- Stabilized-approach assessment
- Flight experience screen

Aerofly connection details depend on the telemetry/control interface actually exposed by the simulator. The app does not claim unsupported bidirectional simulator control.

Checklist assets are intentionally not scraped from copyrighted sources. Put only licensed, public-domain, or user-provided assets in assets/checklists/.
