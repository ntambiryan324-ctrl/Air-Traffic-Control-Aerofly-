# Aerofly Telemetry Map (minimal test build)

This build is intentionally limited to testing two things: a real interactive OpenStreetMap base map and live Aerofly FS Global telemetry. No ATC, flight-planning, or AI features are included in this test version.

## Before testing

1. In Aerofly FS Global, open **Settings → Miscellaneous**.
2. Enable **Send flight data to FSWidgets Apps**. The separate Broadcast flight-info setting is not required for the FSWidgets connection.
3. Keep Aerofly running and open this app.
4. If Aerofly and this app are running on the same Android device, try `127.0.0.1`. If Aerofly runs on another device, enter the simulator device's IPv4 address; both devices must be able to reach each other over the network.
5. The app connects to the simulator's FSWidgets TCP service on port **58585** and sends `GET / HTTP/1.1\r\n\r\n` to start the telemetry stream.
6. The app also listens for XGPS/XATT telemetry on UDP ports **49002** and **40092**.

The app should first show a global map view. When it receives a valid aircraft position, it should center on the aircraft and zoom in. The status line shows received packet count and map tile-loading errors.

## Map source and licensing

The base map uses OpenStreetMap standard raster tiles. Tile downloads are limited to the visible viewport, cached locally for repeat visits, and identified with an application User-Agent. The map displays attribution to © OpenStreetMap contributors. See the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Build

GitHub Actions builds an Android ARM64 debug APK using Buildozer. The workflow checks Python syntax, builds the APK, verifies that it exists, uploads an artifact, and attaches the APK to a GitHub release.
