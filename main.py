import os
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_WINDOW", "sdl2")

from kivy.config import Config
Config.set("graphics", "multisamples", "0")
Config.set("graphics", "vsync", "0")
Config.set("graphics", "maxfps", "60")

from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

PALETTES = {
    "Aviation Blue": ((0.035, 0.050, 0.080, 1), (0.075, 0.105, 0.165, 0.98), (0.13, 0.63, 1.0, 1), (0.16, 0.88, 0.96, 1)),
    "Amber": ((0.055, 0.045, 0.025, 1), (0.115, 0.090, 0.045, 0.98), (1.0, 0.66, 0.12, 1), (1.0, 0.86, 0.35, 1)),
    "Emerald": ((0.025, 0.060, 0.050, 1), (0.055, 0.115, 0.095, 0.98), (0.15, 0.88, 0.55, 1), (0.35, 1.0, 0.72, 1)),
    "Violet": ((0.050, 0.035, 0.075, 1), (0.105, 0.075, 0.145, 0.98), (0.66, 0.40, 1.0, 1), (0.84, 0.65, 1.0, 1)),
}


class Theme:
    dark = True
    palette_name = "Aviation Blue"
    bg, panel, accent, accent2 = PALETTES[palette_name]
    text = (0.94, 0.97, 1.0, 1)
    muted = (0.57, 0.65, 0.76, 1)

    @classmethod
    def apply(cls, palette=None, dark=None):
        if palette in PALETTES:
            cls.palette_name = palette
        if dark is not None:
            cls.dark = dark
        cls.bg, cls.panel, cls.accent, cls.accent2 = PALETTES[cls.palette_name]
        if not cls.dark:
            cls.bg = (0.92, 0.94, 0.97, 1)
            cls.panel = (1.0, 1.0, 1.0, 0.97)
            cls.text = (0.08, 0.10, 0.14, 1)
            cls.muted = (0.34, 0.40, 0.48, 1)
        else:
            cls.text = (0.94, 0.97, 1.0, 1)
            cls.muted = (0.57, 0.65, 0.76, 1)


class Card(BoxLayout):
    def __init__(self, title="", subtitle="", icon="", height=88, **kwargs):
        super().__init__(orientation="vertical", padding=(dp(16), dp(13)), spacing=dp(4), size_hint_y=None, height=dp(height), **kwargs)
        with self.canvas.before:
            Color(0, 0, 0, 0.22)
            self.shadow = RoundedRectangle(pos=(self.x, self.y - dp(3)), size=self.size, radius=[dp(20)])
            Color(*Theme.panel)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
        self.bind(pos=self._sync, size=self._sync)
        head = BoxLayout(size_hint_y=None, height=dp(27), spacing=dp(8))
        if icon:
            head.add_widget(Label(text=icon, color=Theme.accent2, font_size="17sp", size_hint_x=None, width=dp(30)))
        head.add_widget(Label(text=title, color=Theme.text, font_size="13sp", bold=True, halign="left"))
        self.add_widget(head)
        self.add_widget(Label(text=subtitle, color=Theme.muted, font_size="9.5sp", halign="left"))

    def _sync(self, *_):
        self.rect.pos, self.rect.size = self.pos, self.size
        self.shadow.pos, self.shadow.size = (self.x, self.y - dp(3)), self.size


class NavButton(ButtonBehavior, BoxLayout):
    def __init__(self, label, icon, active=False, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(2), padding=(0, dp(6)), **kwargs)
        self.add_widget(Label(text=icon, color=Theme.accent if active else Theme.muted, font_size="18sp"))
        self.add_widget(Label(text=label, color=Theme.accent if active else Theme.muted, font_size="8sp", bold=active))


class TopBar(BoxLayout):
    def __init__(self, title, subtitle="", on_settings=None, **kwargs):
        super().__init__(size_hint_y=None, height=dp(64), padding=(dp(14), dp(9)), spacing=dp(8), **kwargs)
        left = BoxLayout(orientation="vertical", spacing=0)
        left.add_widget(Label(text=title, color=Theme.text, font_size="18sp", bold=True, halign="left"))
        left.add_widget(Label(text=subtitle, color=Theme.muted, font_size="8.5sp", halign="left"))
        self.add_widget(left)
        self.add_widget(Widget())
        gear = NavButton("Settings", "⚙", active=False, size_hint_x=None, width=dp(62))
        if on_settings:
            gear.bind(on_release=on_settings)
        self.add_widget(gear)


class Globe(Widget):
    spin = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.draw, size=self.draw, spin=self.draw)
        self.draw()
        Clock.schedule_interval(self._tick, 1 / 30.0)

    def _tick(self, dt):
        self.spin = (self.spin + dt * 5) % 360

    def draw(self, *_):
        self.canvas.clear()
        cx, cy = self.center
        r = min(self.width, self.height) * 0.39
        with self.canvas:
            Color(0.02, 0.06, 0.12, 1)
            Ellipse(pos=(cx-r, cy-r), size=(2*r, 2*r))
            Color(*Theme.accent)
            Line(ellipse=(cx-r, cy-r, 2*r, 2*r), width=1.3)
            Color(*Theme.accent2, 0.22)
            for k in (-0.65, -0.32, 0, 0.32, 0.65):
                Line(ellipse=(cx-r, cy-r*max(0.25, abs(k)+0.28), 2*r, 2*r*max(0.25, abs(k)+0.28)), width=0.7)
            for k in (-0.55, -0.25, 0, 0.25, 0.55):
                Line(points=[cx+k*r, cy-r, cx+k*r*0.35, cy, cx+k*r, cy+r], width=0.7)
            Color(*Theme.accent2)
            Ellipse(pos=(cx+r*0.08, cy+r*0.12), size=(dp(9), dp(9)))
            Color(*Theme.accent)
            Line(points=[cx+r*0.1, cy+r*0.15, cx+r*0.35, cy+r*0.27, cx+r*0.52, cy+r*0.18], width=1.8)


class SoftButton(ButtonBehavior, Label):
    def __init__(self, text, color=None, **kwargs):
        super().__init__(text=text, color=Theme.text, font_size="9sp", bold=True, halign="center", valign="middle", **kwargs)
        self.fill = color or Theme.panel
        with self.canvas.before:
            Color(*self.fill)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(17)])
        self.bind(pos=lambda *_: setattr(self.rect, "pos", self.pos), size=lambda *_: setattr(self.rect, "size", self.size))

    def on_press(self):
        Animation(opacity=.65, duration=.08).start(self)

    def on_release(self):
        Animation(opacity=1, duration=.16).start(self)


class MapScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()
        root.add_widget(Globe(size_hint=(1, 1), pos_hint={"center": (0.5, 0.53)}))
        top = TopBar("Navigation", "OPENSTREETMAP • ENROUTE • LIVE MAP", on_settings=lambda *_: App.get_running_app().show("settings"))
        top.pos_hint = {"top": 1}; root.add_widget(top)
        chips = BoxLayout(size_hint=(0.94, None), height=dp(42), pos_hint={"center_x": .5, "top": .86}, spacing=dp(7))
        for label in ("OSM", "IFR", "VFR", "WX", "TERRAIN"):
            chips.add_widget(SoftButton(label))
        root.add_widget(chips)
        panel = BoxLayout(orientation="vertical", size_hint=(0.92, None), height=dp(104), pos_hint={"center_x": .5, "y": .15}, padding=dp(14), spacing=dp(4))
        with panel.canvas.before:
            Color(*Theme.panel); panel.rect = RoundedRectangle(pos=panel.pos, size=panel.size, radius=[dp(24)])
        panel.bind(pos=lambda *_: setattr(panel.rect, "pos", panel.pos), size=lambda *_: setattr(panel.rect, "size", panel.size))
        panel.add_widget(Label(text="GLOBAL ENROUTE MAP", color=Theme.accent2, font_size="10sp", bold=True, halign="left"))
        panel.add_widget(Label(text="Airways • VOR/NDB • Waypoints • FIR/UIR • ILS • Airports • Terrain", color=Theme.text, font_size="11sp", halign="left"))
        panel.add_widget(Label(text="Visual shell only — live data layers will be wired after the UI is stable.", color=Theme.muted, font_size="8.5sp", halign="left"))
        root.add_widget(panel)
        self.add_widget(root)


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = FloatLayout()
        with root.canvas.before:
            Color(*Theme.bg); self.bg = RoundedRectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda *_: setattr(self.bg, "pos", root.pos), size=lambda *_: setattr(self.bg, "size", root.size))
        root.add_widget(Globe(size_hint=(1, .63), pos_hint={"top": .92}))
        root.add_widget(TopBar("AeroflyATC", "FLIGHT COMPANION • POCKET-SKY STYLE", on_settings=lambda *_: App.get_running_app().show("settings")))
        card = BoxLayout(orientation="vertical", size_hint=(.92, None), height=dp(118), pos_hint={"center_x": .5, "y": .22}, padding=dp(16), spacing=dp(6))
        with card.canvas.before:
            Color(*Theme.panel); card.rect = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(26)])
        card.bind(pos=lambda *_: setattr(card.rect, "pos", card.pos), size=lambda *_: setattr(card.rect, "size", card.size))
        card.add_widget(Label(text="READY FOR FLIGHT", color=Theme.accent2, font_size="11sp", bold=True, halign="left"))
        card.add_widget(Label(text="Plan • Navigate • Monitor • Communicate", color=Theme.text, font_size="17sp", bold=True, halign="left"))
        card.add_widget(Label(text="Aerofly connection and live telemetry will be added after the visual foundation is stable.", color=Theme.muted, font_size="9sp", halign="left"))
        root.add_widget(card)
        self.add_widget(root)


class PlannerScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_widget(self._build())

    def _build(self):
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(4)), spacing=dp(8))
        root.add_widget(TopBar("Flight Planner", "IFR / VFR • ROUTE GENERATOR • PERFORMANCE", on_settings=lambda *_: App.get_running_app().show("settings")))
        scroll = ScrollView(bar_width=0)
        grid = GridLayout(cols=1, spacing=dp(10), padding=(dp(2), dp(8)), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for icon, title, sub in [
            ("✈", "Route Generator", "Origin → destination • optimized route • airway selection"),
            ("↗", "SID / STAR / APPROACH", "Runway-to-runway planning • procedures • ILS"),
            ("◈", "Aircraft Performance", "80+ aircraft concept • cruise level • airspeed • climb/cruise/descent"),
            ("⛽", "Fuel & Loadsheet", "Fuel burn • reserve • payload • estimated time"),
            ("🌊", "Oceanic Tracks", "NAT / PACOTS planning for long-haul routes"),
            ("△", "Terrain Clearance", "Vertical profile and terrain-clearance presentation"),
            ("⇧", "Export & Networks", "MSFS • X-Plane • VATSIM • IVAO export/prefill"),
            ("▣", "Flight Logbook", "Planned and completed flights — coming later"),
        ]:
            grid.add_widget(Card(title, sub, icon=icon, height=82))
        scroll.add_widget(grid); root.add_widget(scroll)
        return root


class ChartsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(4)), spacing=dp(8))
        root.add_widget(TopBar("Charts & Airports", "WORLDWIDE • DETAILED AIRPORT MAPS", on_settings=lambda *_: App.get_running_app().show("settings")))
        scroll = ScrollView(bar_width=0)
        grid = GridLayout(cols=1, spacing=dp(10), padding=(dp(2), dp(8)), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for title, sub, icon in [
            ("Global Navigation Charts", "Enroute charts with airways, VORs, terrain and weather", "◎"),
            ("Airport Charts", "Runways • taxiways • lighting • frequencies • airport information", "▦"),
            ("ILS / Approaches", "Localizers and approach information", "⌁"),
            ("Airspace", "FIR / UIR boundaries and controlled airspace", "◇"),
            ("Airport Search", "Worldwide search • runway-length filtering • operational information", "⌕"),
            ("Closed Airports", "Closed-airport status presentation", "×"),
        ]:
            grid.add_widget(Card(title, sub, icon=icon, height=82))
        scroll.add_widget(grid); root.add_widget(scroll); self.add_widget(root)


class ToolsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(4)), spacing=dp(8))
        root.add_widget(TopBar("Flight Tools", "WEATHER • TERRAIN • AIRSPACE • SIMULATOR", on_settings=lambda *_: App.get_running_app().show("settings")))
        scroll = ScrollView(bar_width=0)
        grid = GridLayout(cols=1, spacing=dp(10), padding=(dp(2), dp(8)), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for title, sub, icon in [
            ("Live Simulator Tracking", "Moving aircraft • altitude • heading • progress", "●"),
            ("Real-time Weather", "Clouds • precipitation • wind overlays", "☁"),
            ("Terrain & 3D", "Terrain clearance • exaggeration control • future 3D globe", "▲"),
            ("Flight Plan Import", "SimBrief / route import presentation", "⇩"),
            ("Export to Simulator", "MSFS / X-Plane flight-plan export presentation", "⇧"),
            ("AIRAC Navigation Data", "Cycle-aware waypoints, navaids, procedures and airways", "◌"),
        ]:
            grid.add_widget(Card(title, sub, icon=icon, height=82))
        scroll.add_widget(grid); root.add_widget(scroll); self.add_widget(root)


class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(4)), spacing=dp(8))
        root.add_widget(TopBar("Settings", "APPEARANCE • COLOUR • CONNECTIONS", on_settings=lambda *_: None))
        scroll = ScrollView(bar_width=0)
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=(dp(2), dp(8)), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        theme_card = Card("Appearance", "Switch between dark and light mode", icon="◐", height=98)
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        for label, dark in (("DARK", True), ("LIGHT", False)):
            b = SoftButton(label); b.bind(on_release=lambda *_x, d=dark: App.get_running_app().set_theme(dark=d)); row.add_widget(b)
        theme_card.add_widget(row); box.add_widget(theme_card)
        palette = Card("Colour Palette", "Change the accent system without changing layout", icon="✦", height=122)
        prow = GridLayout(cols=4, spacing=dp(7), size_hint_y=None, height=dp(40))
        for name in PALETTES:
            b = SoftButton(name.split()[0].upper(), color=PALETTES[name][2]); b.bind(on_release=lambda *_x, n=name: App.get_running_app().set_theme(palette=n)); prow.add_widget(b)
        palette.add_widget(prow); box.add_widget(palette)
        box.add_widget(Card("Aerofly Connection", "Connect to Aerofly telemetry • TCP/UDP bridge will be wired later", icon="⌁", height=82))
        box.add_widget(Card("Local AI ATC", "Offline model • FAA knowledge • map/terrain/navigation context", icon="AI", height=82))
        box.add_widget(Card("Map Provider", "OpenStreetMap foundation now • other chart providers later", icon="◎", height=82))
        box.add_widget(Card("About", "AeroflyATC • simulation companion • not for real-world operations", icon="ⓘ", height=82))
        scroll.add_widget(box); root.add_widget(scroll); self.add_widget(root)


class ScratchScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=(dp(12), dp(4)), spacing=dp(8))
        root.add_widget(TopBar("Scratchpad", "CRAFT • CLEARANCE • ROUTE • ALTITUDE • FREQUENCY • TRANSPONDER", on_settings=lambda *_: App.get_running_app().show("settings")))
        root.add_widget(Card("CRAFT", "Visual scratchpad foundation — handwriting canvas comes next.", icon="✎", height=80))
        root.add_widget(Widget())
        self.add_widget(root)


class MainNavigation(FloatLayout):
    def __init__(self, manager, **kwargs):
        super().__init__(**kwargs)
        bar = BoxLayout(size_hint=(.96, None), height=dp(68), pos_hint={"center_x": .5, "y": .015}, spacing=dp(3), padding=(dp(6), dp(5)))
        with bar.canvas.before:
            Color(*Theme.panel); bar.rect = RoundedRectangle(pos=bar.pos, size=bar.size, radius=[dp(26)])
            Color(0, 0, 0, .20); bar.shadow = RoundedRectangle(pos=(bar.x, bar.y-dp(3)), size=bar.size, radius=[dp(26)])
        def sync(*_):
            bar.rect.pos, bar.rect.size = bar.pos, bar.size
            bar.shadow.pos, bar.shadow.size = (bar.x, bar.y-dp(3)), bar.size
        bar.bind(pos=sync, size=sync)
        for name, label, icon in (("home", "Home", "⌂"), ("map", "Map", "◎"), ("planner", "Plan", "✈"), ("charts", "Charts", "▦"), ("tools", "Tools", "◈"), ("scratch", "Scratch", "✎")):
            b = NavButton(label, icon, active=(name == "home"))
            b.bind(on_release=lambda *_x, n=name: manager.show(n))
            bar.add_widget(b)
        self.add_widget(bar)


class AeroflyATC(App):
    title = "AeroflyATC"

    def build(self):
        Theme.apply()
        root = FloatLayout()
        self.build_into(root)
        Clock.schedule_once(lambda *_: self._animate(root), .05)
        return root

    def build_into(self, root):
        self.sm = ScreenManager(transition=SlideTransition(duration=.20))
        for screen in (HomeScreen(name="home"), MapScreen(name="map"), PlannerScreen(name="planner"), ChartsScreen(name="charts"), ToolsScreen(name="tools"), ScratchScreen(name="scratch"), SettingsScreen(name="settings")):
            self.sm.add_widget(screen)
        root.add_widget(self.sm)
        root.add_widget(MainNavigation(self.sm))

    def show(self, name):
        if name in self.sm.screen_names:
            self.sm.current = name

    def set_theme(self, dark=None, palette=None):
        Theme.apply(palette=palette, dark=dark)
        self.root.clear_widgets()
        self.build_into(self.root)

    def _animate(self, root):
        root.opacity = 0
        Animation(opacity=1, duration=.35, t="out_quad").start(root)


if __name__ == "__main__":
    AeroflyATC().run()
