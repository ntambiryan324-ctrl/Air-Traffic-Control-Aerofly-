import os
import traceback

# Apply graphics-safe settings before importing any other Kivy modules.
os.environ.setdefault("KIVY_NO_ARGS", "1")
from kivy.config import Config
Config.set("graphics", "multisamples", "0")
Config.set("graphics", "vsync", "0")

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

BG = (0.035, 0.055, 0.085, 1)
CARD = (0.065, 0.095, 0.135, 1)
TEXT = (0.90, 0.94, 0.98, 1)
MUTED = (0.56, 0.64, 0.73, 1)
ACCENT = (0.10, 0.62, 0.95, 1)


class BootShell(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(18), spacing=dp(10), **kwargs)
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)
        self.status = Label(text="Aerofly Flight Companion\n\nStarting safely…", color=TEXT, halign="center", valign="middle")
        self.status.bind(size=lambda *_: setattr(self.status, "text_size", self.status.size))
        self.add_widget(self.status)
        self.retry = Button(text="RETRY FULL APP", size_hint_y=None, height=dp(48), background_normal="", background_color=CARD, color=TEXT)
        self.retry.bind(on_press=lambda *_: self.load_full_app())
        self.retry.disabled = True
        self.add_widget(self.retry)

    def _sync(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def load_full_app(self):
        app = App.get_running_app()
        try:
            self.status.text = "Loading flight systems…"
            # Keep the original implementation intact; only its startup is deferred
            # until SDL/Kivy has a live window and event loop.
            import legacy_main
            legacy = legacy_main.AeroflyCompanion()
            app.legacy = legacy
            root = legacy.build()
            app.root.clear_widgets()
            app.root.add_widget(root)
            self.retry.disabled = True
        except BaseException as exc:
            path = os.path.join(app.user_data_dir, "startup_error.log")
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("\n--- deferred startup failure ---\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            self.status.text = "Startup failure captured.\n\n%s\n\nTap RETRY FULL APP after fixing." % str(exc)
            self.retry.disabled = False


class AeroflyBoot(App):
    def build(self):
        root = BootShell()
        Clock.schedule_once(lambda *_: self._start(root), 0.25)
        return root

    def _start(self, root):
        root.status.text = "Aerofly Flight Companion\n\nInitializing…"
        Clock.schedule_once(lambda *_: root.load_full_app(), 0.35)

    def on_stop(self):
        try:
            if hasattr(self, "legacy"):
                self.legacy.on_stop()
        except Exception:
            pass


if __name__ == "__main__":
    AeroflyBoot().run()
