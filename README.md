# Aerofly ATC — telemetry-first flight deck

Android ARM64 companion for Aerofly FS Global. The architecture prioritizes real simulator telemetry; route planning is a separate layer and must not fabricate live aircraft state.

## Current phase: Phase 2 — route planning and waypoints

- Interactive OpenStreetMap moving map with aircraft overlay when valid telemetry is received.
- Route planner supports up to 40 named waypoints entered as decimal-degree latitude/longitude.
- Airport lookup by ICAO, GPS or IATA code from the public-domain OurAirports dataset. The CSV is downloaded on demand and cached locally; internet access is required on first lookup.
- Planned route line and waypoint markers are drawn over the map.
- Great-circle leg and total distance are calculated in nautical miles.
- Estimated en-route time is shown only when live ground speed is greater than 1 kt; it is a simple distance/speed estimate, not an operational flight plan.
- Waypoints persist in app-private storage and can be exported as GPX 1.1. GPX is a portable waypoint format, **not** an Aerofly custom-mission file.
- A current live aircraft position can be added as a waypoint when valid telemetry is available.

### Route planner limitations

The first route planner uses manual coordinates and airport reference points. It does not yet calculate airway routes, validate airspace, provide SID/STAR procedures, calculate fuel/reserves, or produce a certified/operational flight plan. Airport data is crowd-sourced and supplied without a guarantee of accuracy or fitness for purpose. Verify all navigation data against current authoritative aviation sources before any real-world use.

## Telemetry troubleshooting

1. In Aerofly FS Global, open **Settings → Miscellaneous** and enable **Send flight data to FSWidgets Apps**.
2. Keep Aerofly running and open Aerofly ATC.
3. If both apps run on the same Android device, try `127.0.0.1`. If Aerofly runs on another device, enter that device's IPv4 address; both devices must be able to communicate.
4. The app attempts the FSWidgets TCP service on port **58585** and listens for candidate XGPS/XATT records on UDP ports **49002** and **40092**.
5. Use the on-screen receive byte counter and last-payload preview to distinguish a silent socket from data that arrives but is not parsed. A successful TCP connection alone does not prove telemetry is flowing.

The exact live telemetry format still needs confirmation from a real received payload on the user's Aerofly setup. Do not treat the parser's candidate record formats as confirmed until the diagnostic display captures actual data.

## Data sources and licensing

- **OpenStreetMap:** standard raster tiles from `tile.openstreetmap.org`; visible viewport tiles only, local caching, identifying User-Agent and on-screen attribution. Follow the [official tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
- **OurAirports:** airport reference data downloaded from the [OurAirports data repository](https://github.com/davidmegginson/ourairports-data). OurAirports states its data is public domain, asks for credit, and provides no accuracy or fitness-for-purpose guarantee. Attribution: “Data from OurAirports (https://ourairports.com/).”
- **GPX:** export follows the open GPX 1.1 waypoint structure; it is not presented as a proprietary Aerofly mission export.

No proprietary Navigraph, FlyCharts or FSWidgets source code or restricted navigation database is bundled. The UI takes general workflow inspiration from publicly documented aviation applications and implements its own controls.

## Roadmap

1. **Phase 1 — telemetry + map:** continue diagnosing actual FSWidgets TCP payloads and verify map rendering and aircraft movement on the user's tablet.
2. **Phase 2 — route planning + waypoints:** current focus; coordinate waypoints, airport lookup, map route overlay, distance/ETE and GPX export.
3. **Phase 3 — route usability:** edit/reorder individual waypoints, select a waypoint from the map, import GPX, fit route to map and improve airport search.
4. **Phase 4 — aviation data:** evaluate legally usable navaid/runway datasets and data provenance; add source attribution, freshness indicators and validation. Do not imply airway/SID/STAR support without reliable data.
5. **Phase 5 — flight-planning calculations:** performance profiles, fuel/reserve calculations and route-level estimates with explicit assumptions and editable aircraft data.
6. **Phase 6 — charts and weather:** investigate documented APIs and licensing for chart providers and weather layers; proprietary/subscription content requires appropriate authorization.
7. **Phase 7 — ATC companion features:** add radio/ATC workflows only after telemetry and route planning are stable.
8. **Phase 8 — quality:** automated route-math tests, telemetry parser tests from captured fixtures, lifecycle/background testing, accessibility and on-device verification.

## Build

GitHub Actions builds an Android ARM64 debug APK using Buildozer. The workflow checks Python syntax, builds the APK, verifies that it exists, uploads an artifact, and attaches the APK to a GitHub release. A successful CI build does not replace installation and simulator testing on the target tablet.
