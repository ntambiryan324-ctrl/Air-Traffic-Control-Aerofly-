import React from 'react';
import { TelemetryData } from '../types/aviation';
import { Gauge, Navigation, Compass, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface QuickHUDProps {
  telemetry: TelemetryData;
  targetAlt?: number;
  squawk?: string;
}

export const QuickHUD: React.FC<QuickHUDProps> = ({
  telemetry,
  targetAlt,
  squawk = '1200',
}) => {
  const pitch = telemetry.pitch || 0;
  const roll = telemetry.roll || 0;
  const vs = telemetry.vs || 0;

  return (
    <div className="bg-slate-950/95 border border-cyan-900/50 rounded-xl p-3 shadow-xl backdrop-blur-md text-slate-100 font-mono select-none">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Speed Tape / Box */}
        <div className="flex items-center gap-2.5 bg-slate-900/80 px-3 py-2 rounded-lg border border-slate-800 min-w-[120px]">
          <Gauge className="w-5 h-5 text-cyan-400" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold tracking-wider">AIRSPEED (GS)</div>
            <div className="text-xl font-bold tracking-tight text-cyan-300">
              {telemetry.connected ? `${telemetry.speed}` : '---'}{' '}
              <span className="text-xs font-normal text-cyan-500">KT</span>
            </div>
          </div>
        </div>

        {/* Artificial Horizon / Gyro indicator */}
        <div className="relative w-28 h-14 bg-slate-900 rounded-lg border border-slate-800 overflow-hidden flex items-center justify-center">
          {/* Sky / Ground division with roll & pitch translation */}
          <div
            className="absolute inset-0 transition-transform duration-300 ease-out"
            style={{
              transform: `rotate(${-roll}deg) translateY(${pitch * 1.5}px)`,
            }}
          >
            {/* Sky */}
            <div className="w-[200%] h-[200%] -ml-[50%] -mt-[50%] bg-gradient-to-b from-sky-900 via-sky-800 to-sky-700">
              {/* Pitch graduation lines */}
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
                <div className="w-8 h-[1px] bg-white/40" />
                <div className="w-12 h-[1px] bg-white/60" />
                <div className="w-6 h-[1px] bg-white/40" />
              </div>
            </div>
            {/* Horizon bar */}
            <div className="absolute top-1/2 left-0 right-0 h-[2px] bg-white shadow-sm shadow-white/50" />
            {/* Ground */}
            <div className="w-[200%] h-[200%] -ml-[50%] bg-gradient-to-b from-amber-950 to-amber-900" />
          </div>

          {/* Fixed Aircraft Reticle */}
          <div className="relative z-10 flex items-center justify-center">
            <div className="w-4 h-[2px] bg-amber-400 shadow-md" />
            <div className="w-2 h-2 rounded-full border-2 border-amber-400 mx-1" />
            <div className="w-4 h-[2px] bg-amber-400 shadow-md" />
          </div>

          <div className="absolute bottom-0.5 right-1 text-[9px] text-slate-300 font-bold bg-slate-950/80 px-1 rounded z-20">
            {roll !== 0 ? `${Math.round(roll)}°` : 'LEVEL'}
          </div>
        </div>

        {/* Altitude Box */}
        <div className="flex items-center gap-2.5 bg-slate-900/80 px-3 py-2 rounded-lg border border-slate-800 min-w-[130px]">
          <Navigation className="w-5 h-5 text-emerald-400" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold tracking-wider">ALTITUDE (MSL)</div>
            <div className="text-xl font-bold tracking-tight text-emerald-300">
              {telemetry.connected ? telemetry.alt.toLocaleString() : '---'}{' '}
              <span className="text-xs font-normal text-emerald-500">FT</span>
            </div>
          </div>
        </div>

        {/* Vertical Speed */}
        <div className="flex items-center gap-2.5 bg-slate-900/80 px-3 py-2 rounded-lg border border-slate-800 min-w-[110px]">
          {vs >= 0 ? (
            <ArrowUpRight
              className={`w-5 h-5 ${vs > 100 ? 'text-cyan-400' : 'text-slate-500'}`}
            />
          ) : (
            <ArrowDownRight
              className={`w-5 h-5 ${vs < -100 ? 'text-amber-400' : 'text-slate-500'}`}
            />
          )}
          <div>
            <div className="text-[10px] text-slate-400 font-bold tracking-wider">V/S RATE</div>
            <div
              className={`text-base font-bold ${
                vs > 100 ? 'text-cyan-300' : vs < -100 ? 'text-amber-300' : 'text-slate-300'
              }`}
            >
              {telemetry.connected ? `${vs > 0 ? '+' : ''}${vs}` : '---'}{' '}
              <span className="text-xs font-normal text-slate-500">FPM</span>
            </div>
          </div>
        </div>

        {/* Heading Compass */}
        <div className="flex items-center gap-2.5 bg-slate-900/80 px-3 py-2 rounded-lg border border-slate-800 min-w-[110px]">
          <Compass className="w-5 h-5 text-amber-400" />
          <div>
            <div className="text-[10px] text-slate-400 font-bold tracking-wider">HEADING</div>
            <div className="text-xl font-bold tracking-tight text-amber-300">
              {telemetry.connected ? `${telemetry.heading.toString().padStart(3, '0')}°` : '---'}
            </div>
          </div>
        </div>

        {/* Squawk Box */}
        <div className="flex items-center gap-2 bg-slate-900/80 px-3 py-2 rounded-lg border border-slate-800 min-w-[95px]">
          <div>
            <div className="text-[10px] text-slate-400 font-bold tracking-wider">XPDR</div>
            <div className="text-sm font-bold tracking-widest text-emerald-400 font-mono">
              {squawk}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
