import React, { useState, useEffect, useRef } from 'react';
import { ATCMessage, Airport, DecodedMetar, RadioState, TelemetryData } from '../types/aviation';
import { ATCEngine, normalize } from '../core/atcEngine';
import { audioSynthesizer } from '../services/audioSynthesizer';
import {
  Mic,
  MicOff,
  Radio,
  Send,
  Volume2,
  VolumeX,
  AlertTriangle,
  CheckCircle,
  HelpCircle,
  ArrowRightLeft,
  Headphones,
} from 'lucide-react';

interface ATCCommsProps {
  atcEngine: ATCEngine;
  callsign: string;
  origin: Airport;
  dest: Airport;
  telemetry: TelemetryData;
  originMetar: DecodedMetar | null;
}

export const ATCComms: React.FC<ATCCommsProps> = ({
  atcEngine,
  callsign,
  origin,
  dest,
  telemetry,
  originMetar,
}) => {
  const [messages, setMessages] = useState<ATCMessage[]>([
    {
      id: 'init-1',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      sender: 'SYSTEM',
      callsign: 'SYS',
      text: `Aerofly Air Control ATC active for ${callsign}. Departure: ${origin.icao}, Destination: ${dest.icao}.`,
    },
  ]);

  const [inputMessage, setInputMessage] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [radioState, setRadioState] = useState<RadioState>({
    com1Active: 118.7,
    com1Standby: 121.9,
    com2Active: 124.3,
    com2Standby: 121.5,
    activeRadio: 'COM1',
    squawk: '1200',
    transponderMode: 'ALT',
  });

  const chatBottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

  // Initialize Speech Recognition
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onresult = (event: any) => {
          const transcript = event.results[0][0].transcript;
          if (transcript) {
            handleSendMessage(transcript);
          }
          setIsListening(false);
        };

        recognition.onerror = () => {
          setIsListening(false);
        };

        recognition.onend = () => {
          setIsListening(false);
        };

        recognitionRef.current = recognition;
      }
    }
  }, []);

  // Auto-scroll chat to bottom
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = (textToSend?: string) => {
    const text = (textToSend || inputMessage).trim();
    if (!text) return;

    audioSynthesizer.playSquelch();

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    // Append Pilot message
    const pilotMsg: ATCMessage = {
      id: `pilot-${Date.now()}`,
      timestamp,
      sender: 'PILOT',
      callsign,
      text,
    };

    setMessages((prev) => [...prev, pilotMsg]);
    setInputMessage('');

    // Handle with ATC Engine
    setTimeout(() => {
      const atcReply = atcEngine.handle(text, {
        lat: telemetry.lat,
        lon: telemetry.lon,
        alt_ft: telemetry.alt,
        speed_kt: telemetry.speed,
        heading: telemetry.heading,
      });

      if (atcReply) {
        const isError = atcReply.includes('negative') || atcReply.includes('say again');
        const atcMsg: ATCMessage = {
          id: `atc-${Date.now()}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          sender: atcReply.startsWith('ATIS:') ? 'ATIS' : 'ATC',
          callsign: atcReply.split(':')[0] || 'ATC',
          text: atcReply,
          isReadbackError: isError,
        };

        setMessages((prev) => [...prev, atcMsg]);

        // Speak response if voice enabled
        if (voiceEnabled) {
          audioSynthesizer.speakATC(atcReply);
        }

        // If squawk assigned, update radio state
        if (atcEngine.squawk) {
          setRadioState((prev) => ({ ...prev, squawk: atcEngine.squawk! }));
        }
      }
    }, 400);
  };

  const handleQuickRequest = (req: string) => {
    handleSendMessage(req);
  };

  const toggleVoiceInput = () => {
    if (!recognitionRef.current) {
      alert('Speech Recognition is not supported on this browser. You can type requests in the input box.');
      return;
    }

    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      try {
        recognitionRef.current.start();
        setIsListening(true);
        audioSynthesizer.playSquelch();
      } catch {
        setIsListening(false);
      }
    }
  };

  const toggleVoiceReplies = () => {
    const nextVal = !voiceEnabled;
    setVoiceEnabled(nextVal);
    audioSynthesizer.setVoiceEnabled(nextVal);
  };

  const swapCom1 = () => {
    audioSynthesizer.playChirp();
    setRadioState((prev) => ({
      ...prev,
      com1Active: prev.com1Standby,
      com1Standby: prev.com1Active,
    }));
  };

  const swapCom2 = () => {
    audioSynthesizer.playChirp();
    setRadioState((prev) => ({
      ...prev,
      com2Active: prev.com2Standby,
      com2Standby: prev.com2Active,
    }));
  };

  const pendingItems = Object.entries(atcEngine.pending);

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-5 text-slate-100 font-mono select-none">
      {/* Radio Frequency & Transponder Stack */}
      <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-4 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Radio className="w-5 h-5 text-cyan-400" />
            <h2 className="text-sm font-bold text-cyan-300">AVIONICS RADIO STACK & COMMS</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleVoiceReplies}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                voiceEnabled
                  ? 'bg-cyan-950/80 text-cyan-300 border-cyan-600'
                  : 'bg-slate-900 text-slate-500 border-slate-800'
              }`}
            >
              {voiceEnabled ? <Volume2 className="w-3.5 h-3.5" /> : <VolumeX className="w-3.5 h-3.5" />}
              <span>{voiceEnabled ? 'VOICE READOUT: ON' : 'VOICE READOUT: MUTED'}</span>
            </button>
          </div>
        </div>

        {/* Frequencies Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-3">
          {/* COM1 Panel */}
          <div
            className={`p-3 rounded-lg border transition-all ${
              radioState.activeRadio === 'COM1'
                ? 'bg-slate-900/90 border-cyan-500/60 shadow-md shadow-cyan-950/50'
                : 'bg-slate-900/50 border-slate-800'
            }`}
          >
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="font-bold text-cyan-400">COM 1 (VHF)</span>
              <button
                onClick={() => setRadioState((p) => ({ ...p, activeRadio: 'COM1' }))}
                className={`px-1.5 py-0.5 rounded text-[10px] ${
                  radioState.activeRadio === 'COM1'
                    ? 'bg-cyan-600 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                MIC 1
              </button>
            </div>
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[10px] text-slate-500 font-bold">ACTIVE</div>
                <div className="text-xl font-bold tracking-wider text-amber-400">
                  {radioState.com1Active.toFixed(3)}
                </div>
              </div>

              <button
                onClick={swapCom1}
                className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 shadow"
                title="Swap Active and Standby Frequency"
              >
                <ArrowRightLeft className="w-4 h-4" />
              </button>

              <div className="text-right">
                <div className="text-[10px] text-slate-500 font-bold">STBY</div>
                <div className="text-base font-bold tracking-wider text-slate-400">
                  {radioState.com1Standby.toFixed(3)}
                </div>
              </div>
            </div>
          </div>

          {/* COM2 Panel */}
          <div
            className={`p-3 rounded-lg border transition-all ${
              radioState.activeRadio === 'COM2'
                ? 'bg-slate-900/90 border-cyan-500/60 shadow-md shadow-cyan-950/50'
                : 'bg-slate-900/50 border-slate-800'
            }`}
          >
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="font-bold text-cyan-400">COM 2 (VHF)</span>
              <button
                onClick={() => setRadioState((p) => ({ ...p, activeRadio: 'COM2' }))}
                className={`px-1.5 py-0.5 rounded text-[10px] ${
                  radioState.activeRadio === 'COM2'
                    ? 'bg-cyan-600 text-white font-bold'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                MIC 2
              </button>
            </div>
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[10px] text-slate-500 font-bold">ACTIVE</div>
                <div className="text-xl font-bold tracking-wider text-amber-400">
                  {radioState.com2Active.toFixed(3)}
                </div>
              </div>

              <button
                onClick={swapCom2}
                className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 shadow"
                title="Swap Active and Standby Frequency"
              >
                <ArrowRightLeft className="w-4 h-4" />
              </button>

              <div className="text-right">
                <div className="text-[10px] text-slate-500 font-bold">STBY</div>
                <div className="text-base font-bold tracking-wider text-slate-400">
                  {radioState.com2Standby.toFixed(3)}
                </div>
              </div>
            </div>
          </div>

          {/* Transponder (XPDR) Panel */}
          <div className="p-3 rounded-lg border border-slate-800 bg-slate-900/50">
            <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
              <span className="font-bold text-emerald-400">TRANSPONDER (XPDR)</span>
              <div className="flex gap-1 text-[10px]">
                {(['STBY', 'ON', 'ALT'] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setRadioState((p) => ({ ...p, transponderMode: m }))}
                    className={`px-1 rounded ${
                      radioState.transponderMode === m
                        ? 'bg-emerald-600 text-white font-bold'
                        : 'text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[10px] text-slate-500 font-bold">ASSIGNED SQUAWK</div>
                <div className="text-2xl font-bold tracking-widest text-emerald-300 font-mono">
                  {radioState.squawk}
                </div>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-slate-500 font-bold">FLIGHT PHASE</div>
                <div className="text-xs font-bold text-cyan-400 uppercase tracking-wider">
                  {atcEngine.phase}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Comms Interface: Chat Window & Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left 3 Cols: Message Log and Input */}
        <div className="lg:col-span-3 bg-slate-950 border border-cyan-900/40 rounded-xl flex flex-col h-[520px] shadow-2xl overflow-hidden">
          {/* Header with Readback status */}
          <div className="p-3 bg-slate-900/90 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs">
              <Headphones className="w-4 h-4 text-cyan-400" />
              <span className="font-bold text-slate-200">ATC COMMUNICATIONS CHANNEL</span>
              <span className="text-slate-500">•</span>
              <span className="text-cyan-400 font-bold">
                {radioState.activeRadio === 'COM1'
                  ? `${radioState.com1Active.toFixed(3)} MHz`
                  : `${radioState.com2Active.toFixed(3)} MHz`}
              </span>
            </div>

            {/* Pending Readback Alert */}
            {pendingItems.length > 0 && (
              <div className="flex items-center gap-1.5 bg-amber-950/80 border border-amber-600/80 px-2 py-0.5 rounded text-[11px] text-amber-300 animate-pulse">
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>
                  READBACK REQUIRED: {pendingItems.map(([k, v]) => `${k} ${v}`).join(', ')}
                </span>
              </div>
            )}
          </div>

          {/* Transcript Scroll Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.map((msg) => {
              const isPilot = msg.sender === 'PILOT';
              const isSystem = msg.sender === 'SYSTEM';
              const isAtis = msg.sender === 'ATIS';

              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isPilot ? 'items-end' : 'items-start'}`}
                >
                  <div className="flex items-center gap-1.5 text-[10px] text-slate-500 mb-0.5">
                    <span className="font-bold text-slate-400">{msg.callsign}</span>
                    <span>{msg.timestamp}</span>
                  </div>

                  <div
                    className={`max-w-[85%] rounded-xl px-4 py-2.5 text-xs font-mono leading-relaxed shadow-md ${
                      isPilot
                        ? 'bg-cyan-950/80 border border-cyan-500/40 text-cyan-100 rounded-tr-none'
                        : isSystem
                        ? 'bg-slate-900 border border-slate-800 text-slate-400 italic rounded-tl-none'
                        : isAtis
                        ? 'bg-emerald-950/80 border border-emerald-500/40 text-emerald-100 rounded-tl-none'
                        : msg.isReadbackError
                        ? 'bg-rose-950/80 border border-rose-500/50 text-rose-100 rounded-tl-none'
                        : 'bg-slate-900 border border-slate-700 text-slate-100 rounded-tl-none'
                    }`}
                  >
                    {msg.text}
                  </div>
                </div>
              );
            })}
            <div ref={chatBottomRef} />
          </div>

          {/* Comms Input Bar */}
          <div className="p-3 bg-slate-900/90 border-t border-slate-800">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendMessage();
              }}
              className="flex items-center gap-2"
            >
              <button
                type="button"
                onClick={toggleVoiceInput}
                className={`p-2.5 rounded-lg border transition-all ${
                  isListening
                    ? 'bg-rose-600 text-white border-rose-400 animate-pulse'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border-slate-700'
                }`}
                title={isListening ? 'Stop Listening' : 'Push To Talk (Voice Recognition)'}
              >
                {isListening ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
              </button>

              <input
                type="text"
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                placeholder="Type transmission or readback (e.g. 'request taxi', 'squawk 4521')..."
                className="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-4 py-2 text-xs sm:text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />

              <button
                type="submit"
                className="p-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold transition-all shadow-md"
                title="Send Transmission"
              >
                <Send className="w-4 h-4" />
              </button>
            </form>
          </div>
        </div>

        {/* Right Col: Quick Phraseology Action Buttons */}
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-4 shadow-xl space-y-4">
          <h3 className="text-xs font-bold text-cyan-400 border-b border-slate-800 pb-2">
            STANDARD ATC CALLS
          </h3>

          <div className="space-y-1.5">
            <div className="text-[10px] text-slate-500 font-bold uppercase">Pre-Departure</div>
            <button
              onClick={() => handleQuickRequest('request IFR clearance')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request IFR Clearance
            </button>
            <button
              onClick={() => handleQuickRequest('request taxi')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request Push & Taxi
            </button>
            <button
              onClick={() => handleQuickRequest('ready for departure')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Ready for Takeoff
            </button>
          </div>

          <div className="space-y-1.5 pt-1 border-t border-slate-900">
            <div className="text-[10px] text-slate-500 font-bold uppercase">Enroute & Arrival</div>
            <button
              onClick={() => handleQuickRequest(`direct ${dest.icao}`)}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request Direct {dest.icao}
            </button>
            <button
              onClick={() => handleQuickRequest(`climb and maintain FL360`)}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request FL360
            </button>
            <button
              onClick={() => handleQuickRequest(`inbound ${dest.icao}`)}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Inbound for Approach
            </button>
            <button
              onClick={() => handleQuickRequest('request landing')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request Landing Clearance
            </button>
          </div>

          <div className="space-y-1.5 pt-1 border-t border-slate-900">
            <div className="text-[10px] text-slate-500 font-bold uppercase">Advisories & Urgency</div>
            <button
              onClick={() => handleQuickRequest('request atis')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Request Airport ATIS
            </button>
            <button
              onClick={() => handleQuickRequest('say again')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Say Again
            </button>
            <button
              onClick={() => handleQuickRequest('radio check')}
              className="w-full text-left px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-xs text-slate-300 hover:text-cyan-300 transition-colors"
            >
              Radio Check
            </button>
            <button
              onClick={() => handleQuickRequest('MAYDAY MAYDAY engine failure')}
              className="w-full text-left px-3 py-1.5 rounded bg-rose-950/60 hover:bg-rose-900/80 border border-rose-800/80 text-xs text-rose-300 font-bold transition-colors"
            >
              🚨 MAYDAY Emergency
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
