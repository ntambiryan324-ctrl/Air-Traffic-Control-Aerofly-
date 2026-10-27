import React from 'react';
import {
  Plane,
  Compass,
  FileText,
  Radio,
  Sliders,
  Wifi,
  Play,
  Pause,
  FastForward,
  RotateCcw,
} from 'lucide-react';
import { TelemetryData } from '../types/aviation';

interface NavbarProps {
  activeTab: 'GLOBE' | 'PLAN' | 'ATC' | 'TOOLS' | 'LINK';
  setActiveTab: (tab: 'GLOBE' | 'PLAN' | 'ATC' | 'TOOLS' | 'LINK') => void;
  telemetry: TelemetryData;
  isSimRunning: boolean;
  onToggleSim: () => void;
  simMultiplier: number;
  onCycleMultiplier: () => void;
  onResetSim: () => void;
  callsign: string;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  telemetry,
  isSimRunning,
  onToggleSim,
  simMultiplier,
  onCycleMultiplier,
  onResetSim,
  callsign,
}) => {
  const tabs = [
    { id: 'GLOBE', label: 'RADAR MAP', icon: Compass },
    { id: 'PLAN', label: 'FLIGHT PLAN', icon: FileText },
    { id: 'ATC', label: 'ATC COMMS', icon: Radio },
    { id: 'TOOLS', label: 'EFB TOOLS', icon: Sliders },
    { id: 'LINK', label: 'SIM LINK', icon: Wifi },
  ] as const;

  return (
    <header className="bg-slate-950 border-b border-cyan-900/40 text-slate-100 select-none sticky top-0 z-50 shadow-lg shadow-black/40">
      <div className="max-w-7xl mx-auto px-3 sm:px-6">
        <div className="flex items-center justify-between h-14 sm:h-16 gap-2">
          {/* Logo & Callout */}
          <div className="flex items-center gap-2.5 min-w-max">
            <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-lg bg-gradient-to-br from-cyan-600 to-blue-700 flex items-center justify-center shadow-md shadow-cyan-500/20 ring-1 ring-cyan-400/40">
              <Plane className="w-5 h-5 text-white transform -rotate-45" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono font-bold tracking-wider text-sm sm:text-base text-cyan-300">
                  AEROFLY
                </span>
                <span className="font-mono font-light text-slate-400 text-xs sm:text-sm">
                  AIR CONTROL
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-cyan-950 text-cyan-400 border border-cyan-800/60 hidden md:inline-block">
                  v4.1 EFB
                </span>
              </div>
              <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                <span className="text-cyan-400 font-semibold">{callsign}</span>
                <span className="text-slate-600">•</span>
                <span className="flex items-center gap-1">
                  <span
                    className={`inline-block w-2 h-2 rounded-full ${
                      telemetry.connected
                        ? isSimRunning
                          ? 'bg-amber-400 animate-pulse'
                          : 'bg-emerald-400 animate-pulse'
                        : 'bg-rose-500'
                    }`}
                  />
                  <span className="text-[10px] uppercase tracking-wide">
                    {telemetry.connected
                      ? isSimRunning
                        ? `SIM (${simMultiplier}x)`
                        : telemetry.transport
                      : 'STANDBY'}
                  </span>
                </span>
              </div>
            </div>
          </div>

          {/* Quick Telemetry Bar (Desktop) */}
          <div className="hidden lg:flex items-center gap-3 bg-slate-900/80 px-3 py-1.5 rounded-lg border border-slate-800 font-mono text-xs text-slate-300">
            <div className="flex flex-col items-center leading-tight">
              <span className="text-[9px] text-slate-500 tracking-wider">IAS</span>
              <span className="font-bold text-cyan-300">
                {telemetry.connected ? `${telemetry.speed} KT` : '---'}
              </span>
            </div>
            <div className="h-5 w-[1px] bg-slate-800" />
            <div className="flex flex-col items-center leading-tight">
              <span className="text-[9px] text-slate-500 tracking-wider">ALT</span>
              <span className="font-bold text-emerald-400">
                {telemetry.connected ? `${telemetry.alt.toLocaleString()} FT` : '---'}
              </span>
            </div>
            <div className="h-5 w-[1px] bg-slate-800" />
            <div className="flex flex-col items-center leading-tight">
              <span className="text-[9px] text-slate-500 tracking-wider">HDG</span>
              <span className="font-bold text-amber-300">
                {telemetry.connected
                  ? `${telemetry.heading.toString().padStart(3, '0')}°`
                  : '---'}
              </span>
            </div>
            <div className="h-5 w-[1px] bg-slate-800" />
            <div className="flex flex-col items-center leading-tight">
              <span className="text-[9px] text-slate-500 tracking-wider">V/S</span>
              <span
                className={`font-bold ${
                  (telemetry.vs || 0) > 100
                    ? 'text-cyan-400'
                    : (telemetry.vs || 0) < -100
                    ? 'text-amber-400'
                    : 'text-slate-400'
                }`}
              >
                {telemetry.connected
                  ? `${(telemetry.vs || 0) > 0 ? '+' : ''}${telemetry.vs || 0} FPM`
                  : '---'}
              </span>
            </div>
          </div>

          {/* Simulator Quick Action Control */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={onToggleSim}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-mono font-medium transition-all shadow-sm ${
                isSimRunning
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/50 hover:bg-amber-500/30'
                  : 'bg-cyan-600/20 text-cyan-300 border border-cyan-500/50 hover:bg-cyan-600/30'
              }`}
              title={isSimRunning ? 'Pause Flight Simulation' : 'Start Built-in Flight Simulation'}
            >
              {isSimRunning ? (
                <>
                  <Pause className="w-3.5 h-3.5 fill-current" />
                  <span className="hidden sm:inline">SIM ACTIVE</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span className="hidden sm:inline">FLY DEMO</span>
                </>
              )}
            </button>

            {isSimRunning && (
              <>
                <button
                  onClick={onCycleMultiplier}
                  className="px-2 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 text-[11px] font-mono border border-slate-700"
                  title="Cycle Simulation Speed (1x, 2x, 5x, 10x)"
                >
                  <span className="flex items-center gap-0.5">
                    <FastForward className="w-3 h-3" />
                    {simMultiplier}x
                  </span>
                </button>
                <button
                  onClick={onResetSim}
                  className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 border border-slate-700"
                  title="Reset Flight to Departure Airport"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </button>
              </>
            )}
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex space-x-1 overflow-x-auto py-1 scrollbar-none border-t border-slate-900/60">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 py-2 px-3 sm:px-4 rounded-md text-xs sm:text-sm font-mono tracking-wide transition-all whitespace-nowrap ${
                  isActive
                    ? 'bg-cyan-950/80 text-cyan-300 border-b-2 border-cyan-400 font-bold shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/50'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-cyan-400' : 'text-slate-500'}`} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
};
