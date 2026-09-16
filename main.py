import os
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_WINDOW", "sdl2")
from kivy.config import Config
Config.set("graphics", "multisamples", "0")
Config.set("graphics", "vsync", "0")
Config.set("graphics", "maxfps", "60")

import math
import threading
import urllib.request
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.metrics import dp
from kivy.uix.image import Image
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget

BG = (0.035, 0.045, 0.065, 1)
PANEL = (0.07, 0.09, 0.13, 0.96)
PANEL2 = (0.10, 0.13, 0.19, 0.98)
BLUE = (0.12, 0.65, 1.0, 1)
CYAN = (0.15, 0.9, 0.95, 1)
AMBER = (1.0, 0.68, 0.16, 1)
WHITE = (0.94, 0.97, 1, 1)
MUTED = (0.58, 0.67, 0.78, 1)


def rounded(widget, color=PANEL, radius=20):
    with widget.canvas.before:
        Color(*color)
        rr = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
    widget.bind(pos=lambda *_: setattr(rr, "pos", widget.pos), size=lambda *_: setattr(rr, "size", widget.size))
    return rr


class Pill(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("color", WHITE)
        super().__init__(**kwargs)
        rounded(self, PANEL2, 18)


class AircraftMarker(Widget):
    def __init__(self, **kwargs):
        super().__init__(size_hint=(None, None), size=(dp(42), dp(42)), **kwargs)
        with self.canvas:
            Color(*CYAN)
            self.line = Line(points=[], width=2.2, close=True)
            Color(*BLUE)
            self.dot = Ellipse(size=(dp(9), dp(9)))
        self.bind(pos=self.redraw)
        self.redraw()
        self.anim = Animation(opacity=0.55, duration=0.8) + Animation(opacity=1, duration=0.8)
        self.anim.repeat = True
        self.anim.start(self)

    def redraw(self, *_):
        x, y = self.center
        self.line.points = [x, y + 17, x + 7, y - 11, x, y - 5, x - 7, y - 11]
        self.dot.pos = (x - 4.5, y - 4.5)


class MapView(FloatLayout):
    TILE_SIZE = 256
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat = 0.31
        self.lon = 32.58
        self.zoom = 7
        self.tiles = []
        with self.canvas.before:
            Color(*BG)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[0])
            Color(0.16, 0.22, 0.30, 0.7)
            self.grid = Line(points=[], width=1)
        self.bind(pos=self._sync, size=self._sync)
        self.aircraft = AircraftMarker(pos_hint={"center": (0.5, 0.5)})
        self.add_widget(self.aircraft)
        self.empty = Label(text="OPENSTREETMAP\nLoading map…", color=MUTED, halign="center", font_size="13sp", size_hint=(1, 1))
        self.add_widget(self.empty)
        Clock.schedule_once(lambda *_: self.load_tiles(), 0.2)

    def _sync(self, *_):
        self.bg.pos, self.bg.size = self.pos, self.size
        self.grid.points = [self.x, self.center_y, self.right, self.center_y, self.center_x, self.y, self.center_x, self.top]

    def _tile_xy(self, lat, lon):
        n = 2 ** self.zoom
        x = (lon + 180.0) / 360.0 * n
        lat_r = math.radians(max(-85.0511, min(85.0511, lat)))
        y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
        return x, y

    def _url(self, x, y):
        n = 2 ** self.zoom
        return f"https://tile.openstreetmap.org/{self.zoom}/{x % n}/{y % n}.png"

    def load_tiles(self):
        cx, cy = self._tile_xy(self.lat, self.lon)
        tx, ty = int(cx), int(cy)
        root = Path(App.get_running_app().user_data_dir) / "osm"
        root.mkdir(parents=True, exist_ok=True)
        targets = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                x, y = tx + dx, ty + dy
                path = root / f"{self.zoom}_{x}_{y}.png"
                targets.append((x, y, path, self._url(x, y)))
        self.empty.text = "OPENSTREETMAP\nFetching tiles…"
        threading.Thread(target=self._download_tiles, args=(targets,), daemon=True).start()

    def _download_tiles(self, targets):
        for x, y, path, url in targets:
            try:
                if not path.exists() or path.stat().st_size < 1000:
                    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/2.0 OSM map"})
                    with urllib.request.urlopen(req, timeout=12) as src, open(path, "wb") as dst:
                        dst.write(src.read())
                Clock.schedule_once(lambda *_: self._show_tile(path, x, y), 0)
            except Exception:
                pass
        Clock.schedule_once(lambda *_: setattr(self.empty, "text", "OSM MAP • offline tiles unavailable"), 0.2)

    def _show_tile(self, path, tx, ty):
        try:
            img = Image(source=str(path), allow_stretch=True, keep_ratio=False, size_hint=(None, None), size=(dp(256), dp(256)), opacity=0)
            cx, cy = self._tile_xy(self.lat, self.lon)
            img.pos = (self.center_x + (tx - cx) * dp(256), self.center_y + (cy - ty) * dp(256))
            self.add_widget(img, index=1)
            Animation(opacity=1, duration=0.35).start(img)
            self.tiles.append(img)
            self.empty.text = ""
        except Exception:
            pass


class HomeScreen(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*BG)
            self.bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[0])
        self.bind(pos=lambda *_: setattr(self.bg, "pos", self.pos), size=lambda *_: setattr(self.bg, "size", self.size))
        self.map = MapView(size_hint=(1, 1))
        self.add_widget(self.map)

        top = BoxLayout(size_hint=(1, None), height=dp(72), padding=(dp(12), dp(12)), spacing=dp(8))
        title = Label(text="AEROFLY[ATC]", color=WHITE, font_size="20sp", bold=True, halign="left")
        top.add_widget(title)
        status = Label(text="● OFFLINE ATC", color=AMBER, font_size="10sp", size_hint_x=None, width=dp(100))
        top.add_widget(status)
        settings = Pill(text="⚙", size_hint_x=None, width=dp(48), font_size="20sp")
        top.add_widget(settings)
        self.add_widget(top)

        info = BoxLayout(orientation="vertical", size_hint=(.92, None), height=dp(82), pos_hint={"center_x": .5, "y": .13}, padding=dp(12), spacing=dp(4))
        rounded(info, PANEL, 22)
        info.add_widget(Label(text="NO SIMULATOR CONNECTION", color=AMBER, bold=True, font_size="11sp", halign="left"))
        info.add_widget(Label(text="Connect Aerofly later • map remains usable now", color=MUTED, font_size="10sp"))
        self.add_widget(info)

        bottom = BoxLayout(size_hint=(1, None), height=dp(72), padding=(dp(10), dp(10)), spacing=dp(7))
        for text in ("⌁ MAP", "✈ FLIGHT", "◉ COMMS", "✎ SCRATCH"):
            b = Pill(text=text, font_size="9sp")
            bottom.add_widget(b)
        self.add_widget(bottom)

        Clock.schedule_once(lambda *_: self._animate_in(top, info, bottom), 0.1)

    def _animate_in(self, *widgets):
        for w in widgets:
            w.opacity = 0
            Animation(opacity=1, duration=.45, t="out_quad").start(w)


class AeroflyATC(App):
    title = "Aerofly ATC"
    def build(self):
        return HomeScreen()


if __name__ == "__main__":
    AeroflyATC().run()
