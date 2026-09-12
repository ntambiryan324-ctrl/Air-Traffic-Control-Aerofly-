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
