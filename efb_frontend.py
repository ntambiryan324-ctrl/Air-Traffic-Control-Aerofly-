from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Line, Rectangle, Ellipse
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty, ListProperty
from kivy.uix.widget import Widget
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
import os

KV = r"""
#:import dp kivy.metrics.dp

<DarkButton@Button>:
    background_normal: ""
    background_down: ""
    background_color: (0.102,0.102,0.102,1) if not self.state == "down" else (0.20,0.20,0.20,1)
    color: (1,0.694,0,1) if self.disabled else (1,1,1,1)
    font_size: "11sp"
    bold: True
    border: 0,0,0,0

<AmberButton@Button>:
    background_normal: ""
    background_down: ""
    background_color: (1,0.694,0,1)
    color: (0.05,0.05,0.05,1)
    font_size: "11sp"
    bold: True

<Panel@BoxLayout>:
    padding: dp(12)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: (0.102,0.102,0.102,1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]

<TopBar@BoxLayout>:
    size_hint_y: None
    height: dp(58)
    padding: dp(10), dp(6)
    spacing: dp(8)
    Label:
        text: root.title
        color: 1,1,1,1
        font_size: "21sp"
        bold: True
        halign: "left"
        valign: "middle"
    MDIconButton:
        icon: "cog-outline"
        theme_icon_color: "Custom"
        icon_color: 1,0.694,0,1
        size_hint_x: None
        width: dp(48)
        on_release: app.show_settings()

<BottomNav>:
    size_hint_y: None
    height: dp(68)
    padding: dp(3), dp(4)
    spacing: dp(2)
    canvas.before:
        Color:
            rgba: 0.075,0.075,0.075,1
        Rectangle:
            pos: self.pos
            size: self.size
    NavItem:
        icon: "view-grid-outline"
        label: "Home"
        active: app.current_tab == "home"
        on_release: app.switch_tab("home")
    NavItem:
        icon: "airplane"
        label: "My Flight"
        active: app.current_tab == "flight"
        on_release: app.switch_tab("flight")
    NavItem:
        icon: "headset"
        label: "Comms"
        active: app.current_tab == "comms"
        on_release: app.switch_tab("comms")
    NavItem:
        icon: "pencil-outline"
        label: "Scratchpad"
        active: app.current_tab == "scratch"
        on_release: app.switch_tab("scratch")
    NavItem:
        icon: "map-marker-outline"
        label: "Airports"
        active: app.current_tab == "airports"
        on_release: app.switch_tab("airports")

<NavItem@MDIconButton>:
    icon_size: dp(22)
    theme_icon_color: "Custom"
    icon_color: (1,0.694,0,1) if root.active else (0.50,0.50,0.50,1)

<MyFlight>:
    name: "flight"
    BoxLayout:
        orientation: "vertical"
        spacing: dp(0)
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "My Flight"
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            padding: dp(10), dp(4)
            spacing: dp(6)
            canvas.before:
                Color:
                    rgba: 0.051,0.051,0.051,0.88
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(18)]
            MDIconButton:
                icon: "layers-outline"
                theme_icon_color: "Custom"
                icon_color: 1,1,1,1
            MDIconButton:
                icon: "weather-partly-cloudy"
                theme_icon_color: "Custom"
                icon_color: 1,1,1,1
            MDIconButton:
                icon: "radar"
                theme_icon_color: "Custom"
                icon_color: 1,1,1,1
            MDIconButton:
                icon: "crosshairs-gps"
                theme_icon_color: "Custom"
                icon_color: 1,0.694,0,1
            MDIconButton:
                icon: "filter-variant"
                theme_icon_color: "Custom"
                icon_color: 1,1,1,1
        FloatLayout:
            id: map_area
            FlightMap:
                size_hint: 1,1
            Label:
                text: "WAITING FOR ACTIVE FLIGHT TO BE DETECTED..."
                size_hint: None,None
                size: dp(310),dp(34)
                pos_hint: {"center_x":0.5,"top":0.96}
                color: 0.72,0.72,0.72,1
                font_size: "9sp"
                canvas.before:
                    Color:
                        rgba: 0.03,0.03,0.03,0.78
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(17)]
        TelemetryHUD:
            size_hint_y: None
            height: dp(66)

<Comms>:
    name: "comms"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(7)
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "Comms"
        RadioRow:
            title: "COM 1"
            active: "118.700"
            standby: "122.800"
        RadioRow:
            title: "COM 2"
            active: "121.900"
            standby: "118.100"
        BoxLayout:
            size_hint_y: None
            height: dp(34)
            AmberButton:
                text: "'A' FREQUENCIES"
                size_hint_x: None
                width: dp(125)
        ScrollView:
            do_scroll_x: False
            bar_width: dp(3)
            Label:
                id: chat
                text: "[b]ATC[/b]\n\nATC COMMS READY\nNo radio traffic received yet.\n\n[b]SYSTEM[/b]\nAI ATC channel is ready."
                markup: True
                color: 1,1,1,1
                font_size: "13sp"
                text_size: self.width-dp(20), None
                halign: "left"
                valign: "top"
                padding: dp(10),dp(10)
                size_hint_y: None
                height: max(self.texture_size[1], dp(180))
        BoxLayout:
            size_hint_y: None
            height: dp(38)
            spacing: dp(4)
            ChannelButton:
                text: "COM1"
                active: True
            ChannelButton:
                text: "COM2"
            ChannelButton:
                text: "INT1"
            ChannelButton:
                text: "INT2"
            ChannelButton:
                text: "INT3"
            ChannelButton:
                text: "ATC"
        BoxLayout:
            size_hint_y: None
            height: dp(52)
            spacing: dp(6)
            TextInput:
                id: message
                hint_text: "Type a message..."
                multiline: False
                background_color: 0.102,0.102,0.102,1
                foreground_color: 1,1,1,1
                hint_text_color: 0.45,0.45,0.45,1
                cursor_color: 1,0.694,0,1
                padding: dp(12)
            MDIconButton:
                icon: "microphone"
                theme_icon_color: "Custom"
                icon_color: 1,0.694,0,1
                size_hint_x: None
                width: dp(52)
                on_release: app.ptt_placeholder()
        BottomNav:

<RadioRow@BoxLayout>:
    title: ""
    active: ""
    standby: ""
    size_hint_y: None
    height: dp(55)
    spacing: dp(7)
    Panel:
        padding: dp(8)
        Label:
            text: root.title
            color: 0.55,0.55,0.55,1
            size_hint_x: None
            width: dp(50)
        Label:
            text: root.active
            color: 0.30,0.90,0.52,1
            font_name: app.mono_font
            font_size: "19sp"
            bold: True
        AmberButton:
            text: "⇄"
            size_hint_x: None
            width: dp(50)
        Label:
            text: root.standby
            color: 0.55,0.55,0.55,1
            font_name: app.mono_font
            font_size: "17sp"

<ChannelButton@ToggleButton>:
    active: False
    background_normal: ""
    background_down: ""
    background_color: (1,0.694,0,1) if self.state == "down" else (0.102,0.102,0.102,1)
    color: (0.05,0.05,0.05,1) if self.state == "down" else (0.65,0.65,0.65,1)
    font_size: "9sp"

<TelemetryHUD>:
    orientation: "horizontal"
    padding: dp(4),dp(3)
    spacing: dp(1)
    canvas.before:
        Color:
            rgba: 0.06,0.06,0.06,0.97
        Rectangle:
            pos: self.pos
            size: self.size
    HUDCell:
        title: "ORIGIN"
        value: "---"
    HUDCell:
        title: "DEST"
        value: "---"
    HUDCell:
        title: "TAS"
        value: "---"
    HUDCell:
        title: "ALT"
        value: "---"
    HUDCell:
        title: "HDG"
        value: "---"
    HUDCell:
        title: "ETE"
        value: "---"
    HUDCell:
        title: "TOD"
        value: "---"

<HUDCell@BoxLayout>:
    orientation: "vertical"
    Label:
        text: root.title
        color: 0.48,0.48,0.48,1
        font_size: "8sp"
    Label:
        text: root.value
        color: 1,1,1,1
        font_name: app.mono_font
        font_size: "11sp"
        bold: True

<Scratch>:
    name: "scratch"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "Scratchpad"
        FloatLayout:
            DrawingPad:
                id: pad
                size_hint: 1,1
            BoxLayout:
                orientation: "vertical"
                size_hint: None,1
                width: dp(22)
                pos_hint: {"x":0}
                padding: dp(2),dp(28)
                Label: {text:"C"; color:0.28,0.28,0.28,1}
                Label: {text:"R"; color:0.28,0.28,0.28,1}
                Label: {text:"A"; color:0.28,0.28,0.28,1}
                Label: {text:"F"; color:0.28,0.28,0.28,1}
                Label: {text:"T"; color:0.28,0.28,0.28,1}
        BoxLayout:
            size_hint_y: None
            height: dp(64)
            spacing: dp(8)
            padding: dp(12),dp(7)
            Widget:
            ToolButton:
                icon: "notebook-outline"
            ToolButton:
                icon: "pencil"
                active: True
            ToolButton:
                icon: "eraser"
            ToolButton:
                icon: "trash-can-outline"
                on_release: pad.clear()
            Widget:

<ToolButton@MDIconButton>:
    icon_size: dp(25)
    theme_icon_color: "Custom"
    icon_color: (1,0.694,0,1) if root.active else (0.72,0.72,0.72,1)

<Airports>:
    name: "airports"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(7)
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "Airports"
        BoxLayout:
            size_hint_y: None
            height: dp(48)
            spacing: dp(6)
            TextInput:
                id: search
                hint_text: "Search ICAO or airport..."
                multiline: False
                background_color: 0.102,0.102,0.102,1
                foreground_color: 1,1,1,1
                cursor_color: 1,0.694,0,1
                padding: dp(12)
            AmberButton:
                text: "SEARCH"
                size_hint_x: None
                width: dp(90)
        ScrollView:
            GridLayout:
                cols: 1
                spacing: dp(6)
                size_hint_y: None
                height: self.minimum_height
                AirportCard:
                    icao: "HUEN"
                    name_: "Entebbe International"
                    meta: "UGANDA  •  00°02'N 032°26'E"
                AirportCard:
                    icao: "HKJK"
                    name_: "Jomo Kenyatta International"
                    meta: "KENYA  •  01°19'S 036°56'E"
                AirportCard:
                    icao: "OMDB"
                    name_: "Dubai International"
                    meta: "UAE  •  25°15'N 055°21'E"
                AirportCard:
                    icao: "EGLL"
                    name_: "London Heathrow"
                    meta: "UNITED KINGDOM  •  51°28'N 000°27'W"
                AirportCard:
                    icao: "KJFK"
                    name_: "John F. Kennedy International"
                    meta: "USA  •  40°38'N 073°47'W"
        BottomNav:

<AirportCard@Panel>:
    icao: ""
    name_: ""
    meta: ""
    orientation: "vertical"
    size_hint_y: None
    height: dp(82)
    Label:
        text: root.icao
        color: 1,0.694,0,1
        font_name: app.mono_font
        font_size: "18sp"
        bold: True
        halign: "left"
    Label:
        text: root.name_
        color: 1,1,1,1
        font_size: "13sp"
        halign: "left"
    Label:
        text: root.meta
        color: 0.45,0.45,0.45,1
        font_size: "9sp"
        halign: "left"

<Home>:
    name: "home"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "AeroflyATC"
        Panel:
            orientation: "vertical"
            size_hint_y: None
            height: dp(135)
            Label:
                text: "FLIGHT OPERATIONS"
                color: 1,0.694,0,1
                font_size: "11sp"
                bold: True
            Label:
                text: "Ready for Aerofly FS Global"
                color: 1,1,1,1
                font_size: "21sp"
                bold: True
            Label:
                text: "Connect the simulator to begin live flight monitoring."
                color: 0.48,0.48,0.48,1
                font_size: "11sp"
        GridLayout:
            cols: 2
            spacing: dp(7)
            size_hint_y: None
            height: dp(150)
            Panel:
                orientation: "vertical"
                Label:
                    text: "CONNECTION"
                    color: 0.45,0.45,0.45,1
                Label:
                    text: "OFFLINE"
                    color: 1,0.694,0,1
                    font_name: app.mono_font
                    font_size: "18sp"
            Panel:
                orientation: "vertical"
                Label:
                    text: "AI ATC"
                    color: 0.45,0.45,0.45,1
                Label:
                    text: "STANDBY"
                    color: 1,1,1,1
                    font_name: app.mono_font
                    font_size: "18sp"
            Panel:
                orientation: "vertical"
                Label:
                    text: "FLIGHT LOG"
                    color: 0.45,0.45,0.45,1
                Label:
                    text: "0 SESSIONS"
                    color: 1,1,1,1
                    font_name: app.mono_font
                    font_size: "16sp"
            Panel:
                orientation: "vertical"
                Label:
                    text: "WEATHER"
                    color: 0.45,0.45,0.45,1
                Label:
                    text: "NO DATA"
                    color: 1,1,1,1
                    font_name: app.mono_font
                    font_size: "16sp"
        Widget:
        BottomNav:

<Settings>:
    name: "settings"
    BoxLayout:
        orientation: "vertical"
        padding: dp(8)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: 0.051,0.051,0.051,1
            Rectangle:
                pos: self.pos
                size: self.size
        TopBar:
            title: "Settings"
        Panel:
            orientation: "vertical"
            size_hint_y: None
            height: dp(190)
            Label:
                text: "GEMINI AI"
                color: 1,0.694,0,1
                font_size: "11sp"
                bold: True
            Label:
                text: "API key is stored locally on this device."
                color: 0.48,0.48,0.48,1
                font_size: "10sp"
            TextInput:
                id: gemini_key
                hint_text: "Paste Gemini API key..."
                password: True
                multiline: False
                background_color: 0.055,0.055,0.055,1
                foreground_color: 1,1,1,1
                cursor_color: 1,0.694,0,1
            AmberButton:
                text: "SAVE GEMINI KEY"
                size_hint_y: None
                height: dp(40)
                on_release: app.save_gemini_key(gemini_key.text)
        Panel:
            orientation: "vertical"
            size_hint_y: None
            height: dp(130)
            Label:
                text: "MAP DATA"
                color: 1,0.694,0,1
                font_size: "11sp"
                bold: True
            Label:
                text: "OpenAIP key slot\nAviation chart overlays will be connected later."
                color: 0.48,0.48,0.48,1
            TextInput:
                hint_text: "OpenAIP API key..."
                password: True
                multiline: False
                background_color: 0.055,0.055,0.055,1
                foreground_color: 1,1,1,1
        Widget:
"""

class FlightMap(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.redraw, size=self.redraw)
        self.redraw()
    def redraw(self, *_):
        self.canvas.clear()
        with self.canvas:
            Color(0.055,0.075,0.075,1)
            Rectangle(pos=self.pos, size=self.size)
            Color(0.12,0.16,0.16,0.55)
            step=dp(42)
            x=self.x
            while x <= self.right:
                Line(points=[x,self.y,x,self.top],width=0.6); x+=step
            y=self.y
            while y <= self.top:
                Line(points=[self.x,y,self.right,y],width=0.6); y+=step
            Color(1,0.694,0,0.95)
            cx,cy=self.center
            Ellipse(pos=(cx-dp(5),cy-dp(5)),size=(dp(10),dp(10)))
            Line(circle=(cx,cy,dp(28)),width=1.0)
            Line(points=[cx,cy,cx,cy+dp(70)],width=1.3)

class DrawingPad(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.strokes=[]
        self.current=[]
        self.bind(pos=self.redraw,size=self.redraw)
    def on_touch_down(self,touch):
        if self.collide_point(*touch.pos):
            self.current=[touch.pos]
            self.strokes.append(self.current)
            self.redraw()
            return True
        return super().on_touch_down(touch)
    def on_touch_move(self,touch):
        if self.current and self.collide_point(*touch.pos):
            self.current.append(touch.pos)
            self.redraw()
            return True
        return super().on_touch_move(touch)
    def on_touch_up(self,touch):
        if self.current:
            self.current.append(touch.pos)
            self.current=[]
            self.redraw()
            return True
        return super().on_touch_up(touch)
    def clear(self):
        self.strokes=[]
        self.current=[]
        self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.01,0.01,0.01,1)
            Rectangle(pos=self.pos,size=self.size)
            Color(0.34,0.34,0.34,0.22)
            for stroke in self.strokes:
                if len(stroke)>1:
                    Line(points=[v for p in stroke for v in p],width=dp(2))
            if self.current and len(self.current)>1:
                Line(points=[v for p in self.current for v in p],width=dp(2))

class AeroflyScreen(Screen):
    pass
class MyFlight(Screen):
    pass
class Comms(Screen):
    pass
class Scratch(Screen):
    pass
class Airports(Screen):
    pass
class Home(Screen):
    pass
class Settings(Screen):
    pass

class BottomNav:
    pass

class AeroflyATC(MDApp):
    current_tab=StringProperty("flight")
    mono_font=StringProperty("RobotoMono-Regular.ttf")
    def build(self):
        self.theme_cls.theme_style="Dark"
        self.theme_cls.primary_palette="Amber"
        self.theme_cls.accent_palette="Amber"
        Builder.load_string(KV)
        sm=ScreenManager(transition=FadeTransition(duration=0.10))
        for cls in (Home,MyFlight,Comms,Scratch,Airports):
            sm.add_widget(cls())
        sm.add_widget(Settings())
        self.sm=sm
        root=Screen(name="root")
        root.add_widget(sm)
        sm.current="flight"
        return root
    def switch_tab(self,tab):
        self.current_tab=tab
        self.sm.current=tab
    def show_settings(self):
        self.sm.current="settings"
    def save_gemini_key(self,key):
        # UI-only persistence; no AI/network logic is invoked.
        path=os.path.join(self.user_data_dir,"gemini_api_key.txt")
        try:
            with open(path,"w",encoding="utf-8") as f:f.write(key.strip())
            self.sm.current="flight"
        except OSError:
            pass
    def ptt_placeholder(self):
        pass

if __name__=="__main__":
    AeroflyATC().run()
