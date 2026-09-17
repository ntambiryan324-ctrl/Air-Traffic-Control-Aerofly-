import os
import traceback

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.config import Config
Config.set("graphics", "multisamples", "0")
Config.set("graphics", "vsync", "0")
Config.set("graphics", "maxfps", "60")

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label

class SafeBootApp(App):
    title = "Aerofly Flight Companion"
    def build(self):
        root = BoxLayout(orientation="vertical", padding=24, spacing=16)
        self.status = Label(text="AEROFLY ATC\n\nStarting safely…", halign="center", valign="middle", font_size="18sp")
        self.status.bind(size=lambda instance, value: setattr(instance, "text_size", value))
        root.add_widget(self.status)
        self.error_button = Button(text="Startup diagnostics", size_hint_y=None, height=56, opacity=0, disabled=True)
        root.add_widget(self.error_button)
        Clock.schedule_once(self._load_full_app, 0.75)
        return root
    def _load_full_app(self, _dt):
        try:
            import legacy_main
            legacy = legacy_main.AeroflyCompanion()
            full_root = legacy.build()
            if full_root is None:
                raise RuntimeError("AeroflyCompanion.build() returned None")
            self._legacy = legacy
            self.root.clear_widgets()
            self.root.add_widget(full_root)
            self.status = None
        except BaseException as exc:
            text = "Startup failed:\n\n" + repr(exc)
            try:
                with open(os.path.join(self.user_data_dir, "startup_error.log"), "w", encoding="utf-8") as handle:
                    handle.write(traceback.format_exc())
            except BaseException:
                pass
            self.status.text = text
            self.error_button.opacity = 1
            self.error_button.disabled = False
            self.error_button.bind(on_release=lambda *_: self._write_error_again())
    def _write_error_again(self):
        try:
            with open(os.path.join(self.user_data_dir, "startup_error.log"), "a", encoding="utf-8") as handle:
                handle.write("\n\nManual diagnostics requested.\n")
        except BaseException:
            pass

if __name__ == "__main__":
    SafeBootApp().run()
