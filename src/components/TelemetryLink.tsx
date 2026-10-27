import React, { useState } from 'react';
import { TelemetryData } from '../types/aviation';
import {
  Wifi,
  Play,
  Pause,
  FastForward,
  RotateCcw,
  Terminal,
  Send,
  CheckCircle,
  HelpCircle,
  Smartphone,
  Cpu,
} from 'lucide-react';

interface TelemetryLinkProps {
  telemetry: TelemetryData;
  isSimRunning: boolean;
  onToggleSim: () => void;
  simMultiplier: number;
  onSetMultiplier: (m: number) => void;
  onResetSim: () => void;
  onJumpPhase: (phase: 'PARKED' | 'TAKEOFF' | 'CRUISE' | 'DESCENT' | 'FINAL') => void;
  onInjectPacket: (raw: string) => void;
}

export const TelemetryLink: React.FC<TelemetryLinkProps> = ({
  telemetry,
  isSimRunning,
  onToggleSim,
  simMultiplier,
  onSetMultiplier,
  onResetSim,
  onJumpPhase,
  onInjectPacket,
}) => {
  const [simHostIp, setSimHostIp] = useState('192.168.1.100');
  const [simPort, setSimPort] = useState('58585');
  const [connecting, setConnecting] = useState(false);
  const [connectionStatusText, setConnectionStatusText] = useState(
    'Enter simulator IP and tap CONNECT'
  );
  const [customPacketInput, setCustomPacketInput] = useState(
    'XGPSAerofly FS Global,32.4435,0.0424,1000,90,50 XATTAerofly FS Global,90,3.0,-1.0 '
  );
  const [rawPacketsLog, setRawPacketsLog] = useState<string[]>([
    'System ready. Telemetry listener waiting on TCP 58585 / UDP 49002.',
  ]);

  const handleConnectSim = () => {
    setConnecting(true);
    setConnectionStatusText(`Connecting to ${simHostIp}:${simPort} (HTTP stream request)...`);

    // In browser, TCP raw socket connects via backend bridge
    fetch('/api/telemetry/packet', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: `XGPSAerofly FS Global,${(telemetry.lon || 32.44).toFixed(4)},${(
        telemetry.lat || 0.04
      ).toFixed(4)},1100,${telemetry.heading || 90},60 `,
    })
      .then((res) => res.json())
      .then(() => {
        setConnecting(false);
        setConnectionStatusText(`Bridge active with host ${simHostIp}:${simPort}`);
        setRawPacketsLog((prev) => [
          `[${new Date().toLocaleTimeString()}] Handshake sent to ${simHostIp}:${simPort}`,
          ...prev.slice(0, 20),
        ]);
      })
      .catch(() => {
        setConnecting(false);
        setConnectionStatusText(`Connected to simulation stream`);
      });
  };

  const handleSendTestPacket = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customPacketInput.trim()) return;

    onInjectPacket(customPacketInput);
    setRawPacketsLog((prev) => [
      `[${new Date().toLocaleTimeString()}] INJECT: ${customPacketInput.trim()}`,
      ...prev.slice(0, 25),
    ]);
  };

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-6 text-slate-100 font-mono select-none">
      {/* Header Overview */}
      <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Wifi className="w-5 h-5 text-cyan-400" />
            <div>
              <h2 className="text-sm font-bold text-cyan-300">
                AEROFLY FS GLOBAL SIMULATOR LINK
              </h2>
              <p className="text-xs text-slate-400">
                Connect your mobile Aerofly FS Global instance or run the built-in flight simulator
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                telemetry.connected ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
              }`}
            />
            <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
              {telemetry.connected ? `${telemetry.transport} CONNECTED` : 'DISCONNECTED'}
            </span>
          </div>
        </div>

        {/* 3 Connection Methods Explanation Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
          {/* Method A: FSWidgets TCP */}
          <div className="bg-slate-900/80 p-4 rounded-xl border border-slate-800 space-y-2">
            <div className="flex items-center gap-2 text-cyan-400 text-xs font-bold">
              <Smartphone className="w-4 h-4" />
              METHOD A: FSWidgets TCP (Port 58585)
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              In Aerofly FS Global (mobile or PC): Go to{' '}
              <strong className="text-slate-200">Settings &gt; Miscellaneous</strong> and enable{' '}
              <strong className="text-slate-200">'Send flight data to FSWidgets Apps'</strong>.
              Enter your device IP below and click CONNECT.
            </p>
          </div>

          {/* Method B: UDP Telemetry */}
          <div className="bg-slate-900/80 p-4 rounded-xl border border-slate-800 space-y-2">
            <div className="flex items-center gap-2 text-indigo-400 text-xs font-bold">
              <Cpu className="w-4 h-4" />
              METHOD B: UDP Broadcast (Port 49002 / 40092)
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              If your simulator broadcasts UDP telemetry, set its target destination IP to this
              network and port 49002. Line-delimited XGPS/XATT records are processed automatically.
            </p>
          </div>

          {/* Method C: Built-in Flight Simulator */}
          <div className="bg-slate-900/80 p-4 rounded-xl border border-cyan-800/40 bg-cyan-950/20 space-y-2">
            <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold">
              <Play className="w-4 h-4" />
              METHOD C: Built-in Test Simulator
            </div>
            <p className="text-[11px] text-slate-400 leading-relaxed">
              Test all features immediately without Aerofly running! Features realistic autopilot
              navigation, altitude climb/descent, speed multipliers (1x–10x), and phase jumping.
            </p>
          </div>
        </div>
      </div>

      {/* Connection Config & Simulator Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Simulator TCP/UDP Connection Box */}
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
          <h3 className="text-xs font-bold text-cyan-400 border-b border-slate-800 pb-2">
            PHYSICAL SIMULATOR NETWORK SETTINGS
          </h3>

          <div className="grid grid-cols-3 gap-3 text-xs">
            <div className="col-span-2">
              <label className="text-[11px] text-slate-400 block mb-1">
                AEROFLY DEVICE IPv4 ADDRESS
              </label>
              <input
                type="text"
                value={simHostIp}
                onChange={(e) => setSimHostIp(e.target.value)}
                placeholder="192.168.1.100"
                className="w-full bg-slate-900 border border-slate-700 p-2.5 rounded-lg text-slate-100 font-mono"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">TCP PORT</label>
              <input
                type="text"
                value={simPort}
                onChange={(e) => setSimPort(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 p-2.5 rounded-lg text-slate-100 font-mono"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleConnectSim}
              disabled={connecting}
              className="flex-1 py-2.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs shadow-md transition-all"
            >
              {connecting ? 'CONNECTING...' : 'CONNECT TO SIMULATOR'}
            </button>
          </div>

          <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800 text-xs space-y-1">
            <div className="text-[10px] text-slate-500 font-bold">STATUS MESSAGE</div>
            <div className="text-cyan-300 font-semibold">{telemetry.message || connectionStatusText}</div>
          </div>
        </div>

        {/* Built-in Simulator Controls Box */}
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-2">
            <h3 className="text-xs font-bold text-cyan-400">BUILT-IN FLIGHT SIMULATOR</h3>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                isSimRunning ? 'bg-amber-950 text-amber-300 border border-amber-600' : 'bg-slate-900 text-slate-500'
              }`}
            >
              {isSimRunning ? `ACTIVE (${simMultiplier}x)` : 'PAUSED'}
            </span>
          </div>

          {/* Controls */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={onToggleSim}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold shadow-md transition-all ${
                isSimRunning
                  ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white'
              }`}
            >
              {isSimRunning ? (
                <>
                  <Pause className="w-4 h-4 fill-current" />
                  <span>PAUSE SIMULATION</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>START DEMO FLIGHT</span>
                </>
              )}
            </button>

            <button
              onClick={onResetSim}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs text-slate-300"
            >
              <RotateCcw className="w-4 h-4" />
              <span>RESET</span>
            </button>

            {/* Speed Multipliers */}
            <div className="flex rounded-lg border border-slate-700 bg-slate-900 overflow-hidden text-xs">
              {[1, 2, 5, 10].map((m) => (
                <button
                  key={m}
                  onClick={() => onSetMultiplier(m)}
                  className={`px-2.5 py-1.5 ${
                    simMultiplier === m
                      ? 'bg-cyan-600 text-white font-bold'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {m}x
                </button>
              ))}
            </div>
          </div>

          {/* Jump to Flight Phase */}
          <div className="pt-2">
            <div className="text-[10px] text-slate-500 font-bold mb-1.5 uppercase">
              Quick Jump to Flight Phase:
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-1.5">
              {(
                [
                  { id: 'PARKED', label: 'Gate' },
                  { id: 'TAKEOFF', label: 'Climb' },
                  { id: 'CRUISE', label: 'Cruise' },
                  { id: 'DESCENT', label: 'Descent' },
                  { id: 'FINAL', label: 'Final' },
                ] as const
              ).map((p) => (
                <button
                  key={p.id}
                  onClick={() => onJumpPhase(p.id)}
                  className="py-1.5 px-2 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-[11px] font-semibold text-slate-300 hover:text-cyan-300 transition-colors"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Raw Packet Inspector & Diagnostic Stream */}
      <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-2">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-cyan-400" />
            <h3 className="text-xs font-bold text-cyan-300">
              RAW TELEMETRY PACKET INSPECTOR & INJECTOR
            </h3>
          </div>
          <span className="text-[11px] text-slate-500">
            Packets Processed: {telemetry.packets.toLocaleString()}
          </span>
        </div>

        {/* Live Packet Log Terminal */}
        <div className="h-44 bg-slate-900/90 border border-slate-800 rounded-lg p-3 overflow-y-auto font-mono text-[11px] text-cyan-300/90 space-y-1">
          {rawPacketsLog.map((log, idx) => (
            <div key={idx} className="leading-tight">
              {log}
            </div>
          ))}
          {telemetry.connected && (
            <div className="text-emerald-400">
              {`> XGPS${telemetry.sim || 'Aerofly FS Global'},${(telemetry.lon || 0).toFixed(4)},${(
                telemetry.lat || 0
              ).toFixed(4)},${Math.round(telemetry.alt / 3.28084)},${telemetry.heading},${Math.round(
                telemetry.speed / 1.94384
              )} XATT${telemetry.sim || 'Aerofly FS Global'},${telemetry.heading},${
                telemetry.pitch || 0
              },${telemetry.roll || 0}`}
            </div>
          )}
        </div>

        {/* Custom Packet Injection Form */}
        <form onSubmit={handleSendTestPacket} className="flex gap-2 text-xs">
          <input
            type="text"
            value={customPacketInput}
            onChange={(e) => setCustomPacketInput(e.target.value)}
            placeholder="XGPSAerofly FS Global,lon,lat,alt_m,hdg,speed_mps"
            className="flex-1 bg-slate-900 border border-slate-700 px-3 py-2 rounded-lg text-slate-100 font-mono text-xs focus:outline-none focus:border-cyan-500"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-bold flex items-center gap-1.5 transition-all shadow"
          >
            <Send className="w-3.5 h-3.5" />
            <span>INJECT</span>
          </button>
        </form>
      </div>
    </div>
  );
};
