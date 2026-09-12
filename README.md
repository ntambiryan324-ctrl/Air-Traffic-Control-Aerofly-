# AeroflyATC

Mobile ATC companion prototype for Aerofly FS Global.

## Current features

- Kivy Android UI.
- Telemetry listeners on UDP and TCP ports **49002** and **58585**.
- JSON and simple key=value/key:value telemetry parsing.
- Live altitude, airspeed, heading, position, vertical speed and callsign display.
- AI ATC using Groq's OpenAI-compatible API.
- Offline rule-based ATC fallback when the AI service is unavailable.
- Telemetry context is automatically supplied to AI ATC requests.
- C.R.A.F.T. IFR clearance scratchpad with clearance builder.
- GitHub Actions debug APK build.

## Important telemetry limitation

Listening on ports does not by itself create Aerofly FS Global integration. The simulator or a telemetry bridge must actually send data to one of these ports, and its packet format must be supported by the parser. The app accepts JSON and simple key=value/key:value packets.

## Groq key

Do not put a Groq API key in this repository or inside the APK. Groq explicitly recommends keeping API keys out of source code and client bundles. Enter a key in the Comms screen for local testing, or put a key behind a trusted backend for a public release.

Recommended current model: `openai/gpt-oss-20b`.

## Build

Push to `main` or manually run the **Build Android APK** GitHub Actions workflow. The resulting APK is uploaded as the `AeroflyATC-debug-apk` artifact.


## Direct Aerofly connection

Aerofly FS has built-in FSWidgets support. Enable "Send flight data to FSWidgets Apps" in Settings > Miscellaneous. The documented connection target is TCP port 58585. AeroflyATC now connects to that endpoint directly and parses the ForeFlight-compatible XGPS and XATT records. UDP 49002 remains supported as a fallback.

For Aerofly FS Global and AeroflyATC on the same Android tablet, use 127.0.0.1. If Aerofly is running on another device, enter that device's LAN IPv4 address in the Connect tab.

## Voice and moving map

The Comms tab now provides Android speech recognition for pilot transmissions and Android Text-to-Speech for ATC replies. The Map tab displays the aircraft position, heading and recent track in a lightweight moving/radar display.
