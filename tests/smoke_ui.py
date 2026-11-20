"""Headless UI smoke test: builds the whole interface and fails if startup falls back to the recovery screen."""
import os, sys
os.environ["KIVY_NO_ARGS"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kivy.config import Config
Config.set("graphics", "width", "800"); Config.set("graphics", "height", "1280")
import main
app = main.AeroflyATCApp()
app.build()
err = getattr(app, "startup_error", None)
if err:
    print("STARTUP ERROR:\n" + err)
    sys.exit(1)
from kivy.clock import Clock
for _ in range(5):
    Clock.tick()
print("UI smoke test passed")
