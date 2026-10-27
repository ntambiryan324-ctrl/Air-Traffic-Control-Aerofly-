"""Speech output and input through Android APIs. Every call is guarded: off Android, or if the
device refuses, available stays False and nothing raises. Needs no extra build requirements
(pyjnius ships with Kivy on Android)."""
SPEECH_REQUEST = 4242


class Voice:
    def __init__(self):
        self.tts = None
        self.tts_ready = False
        self.stt_ok = False
        self._on_text = None
        self._keep = []
        try:
            from jnius import autoclass, PythonJavaClass, java_method
            from android import activity
            self._autoclass = autoclass
            self._activity = activity
            self._Activity = autoclass("org.kivy.android.PythonActivity")
            owner = self

            class _InitListener(PythonJavaClass):
                __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]
                __javacontext__ = "app"

                @java_method("(I)V")
                def onInit(self, status):
                    owner._tts_init(status)

            listener = _InitListener()
            self._keep.append(listener)
            TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
            self.tts = TextToSpeech(self._Activity.mActivity, listener)
            activity.bind(on_activity_result=self._result)
            self.stt_ok = True
        except Exception:
            self.tts = None

    @property
    def available(self):
        return self.tts_ready or self.stt_ok

    def _tts_init(self, status):
        try:
            if status == 0:
                Locale = self._autoclass("java.util.Locale")
                self.tts.setLanguage(Locale.US)
                self.tts_ready = True
        except Exception:
            self.tts_ready = False

    def speak(self, text):
        if not self.tts_ready or not text:
            return False
        try:
            self.tts.speak(text, 1, None, "atc")  # 1 = QUEUE_ADD
            return True
        except Exception:
            return False

    def listen(self, on_text):
        """Open the system speech dialog; on_text(str) is called with the best result."""
        if not self.stt_ok:
            return False
        try:
            Intent = self._autoclass("android.content.Intent")
            RI = self._autoclass("android.speech.RecognizerIntent")
            intent = Intent(RI.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RI.EXTRA_LANGUAGE_MODEL, RI.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RI.EXTRA_PROMPT, "Speak to ATC")
            self._on_text = on_text
            self._Activity.mActivity.startActivityForResult(intent, SPEECH_REQUEST)
            return True
        except Exception:
            return False

    def _result(self, request, result, data):
        if request != SPEECH_REQUEST or result != -1 or data is None or not self._on_text:
            return
        try:
            items = data.getStringArrayListExtra("android.speech.extra.RESULTS")
            if items is not None and items.size() > 0:
                self._on_text(str(items.get(0)))
        except Exception:
            pass

    def shutdown(self):
        try:
            if self.tts:
                self.tts.shutdown()
        except Exception:
            pass
