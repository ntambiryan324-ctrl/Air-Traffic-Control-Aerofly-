#!/usr/bin/env bash
# Emulator startup smoke test. Lives in a file because android-emulator-runner
# runs each line of an inline script in a separate shell, which lost $APK.
set -eu
trap 'adb logcat -d -v threadtime > startup-logcat.txt 2>/dev/null || true' EXIT
APK="$(find bin -type f -name '*debug.apk' -print -quit)"
test -n "$APK"
PACKAGE="org.aeroflycompanion.aeroflyatc"
echo "Installing emulator-test APK: $APK"
adb install -r "$APK"
adb shell pm path "$PACKAGE"
adb logcat -c
adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 2>&1 | tee monkey-launch.log
sleep 30
adb logcat -d -v threadtime > startup-logcat.txt
if grep -E "FATAL EXCEPTION|Fatal signal [0-9]+|ANR in $PACKAGE|Process: $PACKAGE|Python for android ended" startup-logcat.txt; then
  echo "ERROR: Android reported a crash, fatal signal, ANR, or Python runtime termination."
  exit 1
fi
PID="$(adb shell pidof "$PACKAGE" | tr -d '\r')"
if [ -z "$PID" ]; then
  echo "ERROR: App process is not running 30 seconds after launch."
  tail -n 200 startup-logcat.txt
  exit 1
fi
if grep -q "No activities found" monkey-launch.log; then
  echo "ERROR: Android could not find a launchable activity."
  exit 1
fi
echo "Startup smoke test passed; process PID=$PID stayed alive for 30 seconds."
