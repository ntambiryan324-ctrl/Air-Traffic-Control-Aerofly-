import os, traceback, time
os.environ.setdefault("KIVY_NO_ARGS","1")
os.environ.setdefault("KIVY_WINDOW","sdl2")
from kivy.config import Config
Config.set("graphics","multisamples","0")
Config.set("graphics","vsync","0")
from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.metrics import dp
from kivy.graphics import Color, RoundedRectangle, Ellipse
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget

BG=(0.025,0.035,0.055,1); PANEL=(0.055,0.075,0.11,1); PANEL2=(0.085,0.115,0.17,1)
BLUE=(0.12,0.62,0.98,1); AMBER=(1.0,0.67,0.16,1); WHITE=(0.94,0.97,1,1); MUTED=(0.55,0.64,0.74,1)

class RoundBox(BoxLayout):
    def __init__(self,color=PANEL,radius=22,**kw):
        super().__init__(**kw)
        self._color=color;self._radius=radius
        with self.canvas.before:
            Color(*color);self._rr=RoundedRectangle(pos=self.pos,size=self.size,radius=[dp(radius)])
        self.bind(pos=self._sync,size=self._sync)
    def _sync(self,*_):self._rr.pos=self.pos;self._rr.size=self.size

class Pulse(Widget):
    def __init__(self,**kw):
        super().__init__(size_hint=(None,None),size=(dp(12),dp(12)),**kw)
        with self.canvas:
            Color(*BLUE,mode="rgba");self.e=Ellipse(pos=self.pos,size=self.size)
        self.bind(pos=self._sync)
        self._anim=Animation(opacity=.25,duration=.7)+Animation(opacity=1,duration=.7)
        self._anim.repeat=True;self._anim.start(self)
    def _sync(self,*_):self.e.pos=self.pos

class BootUI(FloatLayout):
    def __init__(self,**kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG);self.bg=RoundedRectangle(pos=self.pos,size=self.size,radius=[0])
        self.bind(pos=lambda *_:setattr(self.bg,"pos",self.pos),size=lambda *_:setattr(self.bg,"size",self.size))
        card=RoundBox(color=PANEL,radius=28,orientation="vertical",padding=dp(24),spacing=dp(10),
                      size_hint=(.88,.52),pos_hint={"center_x":.5,"center_y":.52})
        title=Label(text="AEROFLY[ATC]",color=WHITE,font_size="28sp",bold=True,size_hint_y=None,height=dp(48))
        sub=Label(text="LOCAL FLIGHT COMPANION",color=BLUE,font_size="11sp",bold=True,size_hint_y=None,height=dp(26))
        self.status=Label(text="Starting safely…",color=MUTED,font_size="12sp")
        self.detail=Label(text="Loading aviation systems",color=MUTED,font_size="9sp",size_hint_y=None,height=dp(28))
        self.retry=Button(text="OPEN SAFE MODE",size_hint_y=None,height=dp(46),background_normal="",background_color=PANEL2,color=WHITE)
        self.retry.bind(on_release=lambda *_:self.start_full())
        self.retry.opacity=0;self.retry.disabled=True
        card.add_widget(title);card.add_widget(sub);card.add_widget(self.status);card.add_widget(self.detail);card.add_widget(self.retry)
        self.add_widget(card)
        self.dot=Pulse(pos=(dp(30),dp(30)));self.add_widget(self.dot)
        Clock.schedule_once(lambda *_:self.start_full(),1.0)
    def start_full(self):
        if getattr(self,"started",False):return
        self.started=True;self.status.text="Initializing flight systems…";self.detail.text="Checking UI and local AI modules"
        Clock.schedule_once(self._load,0.15)
    def _load(self,*_):
        app=App.get_running_app()
        try:
            import legacy_main
            legacy=legacy_main.AeroflyCompanion()
            root=legacy.build()
            app.legacy=legacy
            app.root.clear_widgets();app.root.add_widget(root)
        except BaseException as exc:
            self.started=False
            path=os.path.join(app.user_data_dir,"startup_error.log")
            try:
                with open(path,"a",encoding="utf-8") as f:
                    f.write("\n=== STARTUP FAILURE %s ===\n"%time.strftime("%Y-%m-%d %H:%M:%S"))
                    traceback.print_exc(file=f)
                    f.write("\n%s\n"%repr(exc))
            except Exception:pass
            self.status.text="SAFE MODE — MAIN UI IS ALIVE"
            self.detail.text="The full feature layer failed safely. Nothing is allowed to close the app."
            self.retry.text="RETRY FULL APP";self.retry.disabled=False
            self.retry.opacity=1
            Animation(opacity=1,duration=.25).start(self.retry)

class AeroflyBoot(App):
    def build(self):return BootUI()
    def on_stop(self):
        try:
            if hasattr(self,"legacy"):self.legacy.on_stop()
        except Exception:pass

if __name__=="__main__":AeroflyBoot().run()
