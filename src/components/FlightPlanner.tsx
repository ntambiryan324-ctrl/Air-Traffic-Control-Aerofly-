import React, { useState, useEffect } from 'react';
import { Airport, DecodedMetar, FlightPlan } from '../types/aviation';
import { AIRPORTS } from '../data/airports';
import { AIRCRAFT_PROFILES } from '../data/aircraft';
import {
  decode_metar,
  export_gpx,
  format_plan,
  plan_flight,
  vertical_profile,
} from '../core/plannerCore';
import {
  Cloud,
  Compass,
  Download,
  ExternalLink,
  Fuel,
  Navigation,
  RefreshCw,
  Send,
  Sliders,
  Wind,
} from 'lucide-react';

interface FlightPlannerProps {
  origin: Airport;
  dest: Airport;
  onSetOrigin: (ap: Airport) => void;
  onSetDest: (ap: Airport) => void;
  flightPlan: FlightPlan | null;
  onApplyPlan: (plan: FlightPlan, metarRaw?: string) => void;
}

export const FlightPlanner: React.FC<FlightPlannerProps> = ({
  origin,
  dest,
  onSetOrigin,
  onSetDest,
  flightPlan,
  onApplyPlan,
}) => {
  const [selectedAircraft, setSelectedAircraft] = useState('A320');
  const [cruiseFL, setCruiseFL] = useState(360);
  const [speedOverride, setSpeedOverride] = useState<string>('');
  const [originMetar, setOriginMetar] = useState<DecodedMetar | null>(null);
  const [destMetar, setDestMetar] = useState<DecodedMetar | null>(null);
  const [rawOriginMetar, setRawOriginMetar] = useState<string>('');
  const [rawDestMetar, setRawDestMetar] = useState<string>('');
  const [tafText, setTafText] = useState<string>('');
  const [loadingWeather, setLoadingWeather] = useState(false);
  const [simbriefUser, setSimbriefUser] = useState('');
  const [importingSimbrief, setImportingSimbrief] = useState(false);
  const [copiedNotification, setCopiedNotification] = useState('');

  // Calculate local flight plan
  const computedPlan = plan_flight(
    [
      [origin.lat, origin.lon],
      [dest.lat, dest.lon],
    ],
    selectedAircraft,
    cruiseFL,
    45,
    0.05,
    speedOverride ? parseFloat(speedOverride) : undefined
  );

  const fullPlan: FlightPlan = {
    aircraft: computedPlan.aircraft,
    origin: origin.icao,
    dest: dest.icao,
    distance_nm: computedPlan.distance_nm,
    cruise_fl: computedPlan.cruise_fl,
    tas_kt: computedPlan.tas_kt,
    toc_nm: computedPlan.toc_nm,
    tod_nm: computedPlan.tod_nm,
    ete_min: computedPlan.ete_min,
    fuel_trip_kg: computedPlan.fuel_trip_kg,
    fuel_reserve_kg: computedPlan.fuel_reserve_kg,
    fuel_contingency_kg: computedPlan.fuel_contingency_kg,
    fuel_total_kg: computedPlan.fuel_total_kg,
    waypoints: [
      { ident: origin.icao, lat: origin.lat, lon: origin.lon },
      { ident: dest.icao, lat: dest.lat, lon: dest.lon },
    ],
  };

  const profileData = vertical_profile(computedPlan, 20);

  // Fetch weather for airports
  const fetchWeather = async () => {
    setLoadingWeather(true);
    try {
      // Origin METAR
      const resOrigin = await fetch(`/api/metar?icao=${origin.icao}`);
      if (resOrigin.ok) {
        const data = await resOrigin.json();
        setRawOriginMetar(data.raw || '');
        setOriginMetar(decode_metar(data.raw || ''));
      }

      // Dest METAR
      const resDest = await fetch(`/api/metar?icao=${dest.icao}`);
      if (resDest.ok) {
        const data = await resDest.json();
        setRawDestMetar(data.raw || '');
        setDestMetar(decode_metar(data.raw || ''));
      }

      // Origin TAF
      const resTaf = await fetch(`/api/taf?icao=${origin.icao}`);
      if (resTaf.ok) {
        const data = await resTaf.json();
        setTafText(data.raw || '');
      }
    } catch {
      // Fallback local weather simulation
      const mockRaw = `METAR ${origin.icao} 011200Z 14010KT 9999 FEW030 24/16 Q1018 NOSIG`;
      setRawOriginMetar(mockRaw);
      setOriginMetar(decode_metar(mockRaw));
    } finally {
      setLoadingWeather(false);
    }
  };

  useEffect(() => {
    fetchWeather();
  }, [origin.icao, dest.icao]);

  const handleSwapAirports = () => {
    const temp = origin;
    onSetOrigin(dest);
    onSetDest(temp);
  };

  const handleApplyToSystem = () => {
    onApplyPlan(fullPlan, rawOriginMetar);
    setCopiedNotification('Plan synchronized with ATC & Radar Map!');
    setTimeout(() => setCopiedNotification(''), 3000);
  };

  const handleExportGPX = () => {
    const gpxText = export_gpx(`${origin.icao}-${dest.icao}`, [
      [origin.icao, origin.lat, origin.lon],
      [dest.icao, dest.lat, dest.lon],
    ]);
    const blob = new Blob([gpxText], { type: 'application/gpx+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `AEROFLY_${origin.icao}_${dest.icao}.gpx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyPlanText = () => {
    const text = format_plan(computedPlan, origin.icao, dest.icao);
    navigator.clipboard.writeText(text);
    setCopiedNotification('Flight Plan copied to clipboard!');
    setTimeout(() => setCopiedNotification(''), 3000);
  };

  const handleImportSimbrief = async () => {
    if (!simbriefUser.trim()) return;
    setImportingSimbrief(true);
    try {
      const res = await fetch(`/api/simbrief?username=${encodeURIComponent(simbriefUser.trim())}`);
      if (res.ok) {
        const text = await res.text();
        const parser = new DOMParser();
        const xml = parser.parseFromString(text, 'text/xml');
        const origCode = xml.querySelector('origin icao')?.textContent?.trim().toUpperCase();
        const destCode = xml.querySelector('destination icao')?.textContent?.trim().toUpperCase();

        if (origCode && AIRPORTS[origCode]) onSetOrigin(AIRPORTS[origCode]);
        if (destCode && AIRPORTS[destCode]) onSetDest(AIRPORTS[destCode]);

        setCopiedNotification(`SimBrief OFP imported: ${origCode} -> ${destCode}`);
        setTimeout(() => setCopiedNotification(''), 3500);
      }
    } catch {
      setCopiedNotification('Failed to fetch SimBrief plan');
      setTimeout(() => setCopiedNotification(''), 3000);
    } finally {
      setImportingSimbrief(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-6 text-slate-100 font-mono select-none">
      {/* Top Banner Notification */}
      {copiedNotification && (
        <div className="bg-cyan-900/90 border border-cyan-400 text-cyan-200 px-4 py-2.5 rounded-lg text-sm font-bold flex items-center justify-between shadow-lg">
          <span>{copiedNotification}</span>
        </div>
      )}

      {/* Main Grid: Planning controls & Route overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Flight Configuration */}
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-base font-bold text-cyan-300 flex items-center gap-2">
              <Navigation className="w-5 h-5 text-cyan-400" />
              FLIGHT ROUTE CONFIG
            </h2>
            <button
              onClick={handleSwapAirports}
              className="text-xs text-slate-400 hover:text-cyan-300 px-2 py-1 rounded bg-slate-900 border border-slate-700"
            >
              SWAP ⇄
            </button>
          </div>

          {/* Origin & Destination Selectors */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">ORIGIN (ICAO)</label>
              <select
                value={origin.icao}
                onChange={(e) => {
                  const ap = AIRPORTS[e.target.value];
                  if (ap) onSetOrigin(ap);
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-cyan-300 font-bold focus:border-cyan-500 focus:outline-none"
              >
                {Object.values(AIRPORTS).map((ap) => (
                  <option key={ap.icao} value={ap.icao}>
                    {ap.icao} - {ap.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-[11px] text-slate-400 block mb-1">DESTINATION (ICAO)</label>
              <select
                value={dest.icao}
                onChange={(e) => {
                  const ap = AIRPORTS[e.target.value];
                  if (ap) onSetDest(ap);
                }}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-amber-300 font-bold focus:border-amber-500 focus:outline-none"
              >
                {Object.values(AIRPORTS).map((ap) => (
                  <option key={ap.icao} value={ap.icao}>
                    {ap.icao} - {ap.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Aircraft Profile Selection */}
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">AIRCRAFT PROFILE</label>
            <select
              value={selectedAircraft}
              onChange={(e) => setSelectedAircraft(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2.5 text-sm text-slate-200 font-semibold focus:border-cyan-500 focus:outline-none"
            >
              {Object.values(AIRCRAFT_PROFILES).map((ac) => (
                <option key={ac.code} value={ac.code}>
                  {ac.code} — {ac.name} (Cruise {ac.tas_kt} KT, FL{ac.max_fl} max)
                </option>
              ))}
            </select>
          </div>

          {/* Cruise FL Slider */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-[11px] text-slate-400">CRUISE ALTITUDE</label>
              <span className="text-sm font-bold text-cyan-300">FL{computedPlan.cruise_fl}</span>
            </div>
            <input
              type="range"
              min={30}
              max={AIRCRAFT_PROFILES[selectedAircraft]?.max_fl || 410}
              step={10}
              value={cruiseFL}
              onChange={(e) => setCruiseFL(parseInt(e.target.value, 10))}
              className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-400"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>FL30 (3,000 FT)</span>
              <span>
                FL{AIRCRAFT_PROFILES[selectedAircraft]?.max_fl || 410} (
                {((AIRCRAFT_PROFILES[selectedAircraft]?.max_fl || 410) * 100).toLocaleString()} FT)
              </span>
            </div>
          </div>

          {/* Speed Override Input */}
          <div>
            <label className="text-[11px] text-slate-400 block mb-1">
              SPEED OVERRIDE (OPTIONAL TAS KT)
            </label>
            <input
              type="number"
              placeholder={`Nominal: ${AIRCRAFT_PROFILES[selectedAircraft]?.tas_kt || 450} KT`}
              value={speedOverride}
              onChange={(e) => setSpeedOverride(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          {/* Action Buttons */}
          <div className="pt-2 space-y-2">
            <button
              onClick={handleApplyToSystem}
              className="w-full py-2.5 px-4 rounded-lg bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold text-sm flex items-center justify-center gap-2 shadow-lg shadow-cyan-900/30 transition-all"
            >
              <Send className="w-4 h-4" />
              <span>LOAD PLAN INTO ATC & RADAR</span>
            </button>

            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={handleCopyPlanText}
                className="py-2 px-3 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-semibold text-slate-300 flex items-center justify-center gap-1.5"
              >
                <span>COPY BRIEFING</span>
              </button>
              <button
                onClick={handleExportGPX}
                className="py-2 px-3 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs font-semibold text-slate-300 flex items-center justify-center gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>EXPORT GPX</span>
              </button>
            </div>
          </div>
        </div>

        {/* Center & Right Columns: Performance, Fuel, Profile & Weather */}
        <div className="lg:col-span-2 space-y-6">
          {/* Key Flight Metrics Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="bg-slate-950 border border-cyan-900/30 rounded-xl p-3 shadow-md">
              <div className="text-[10px] text-slate-500 font-bold">TOTAL DISTANCE</div>
              <div className="text-xl font-bold text-cyan-300">
                {computedPlan.distance_nm.toFixed(0)}{' '}
                <span className="text-xs font-normal text-slate-400">NM</span>
              </div>
            </div>

            <div className="bg-slate-950 border border-cyan-900/30 rounded-xl p-3 shadow-md">
              <div className="text-[10px] text-slate-500 font-bold">ESTIMATED TIME</div>
              <div className="text-xl font-bold text-emerald-300">
                {Math.floor(computedPlan.ete_min / 60)}h{' '}
                {(Math.round(computedPlan.ete_min) % 60).toString().padStart(2, '0')}m
              </div>
            </div>

            <div className="bg-slate-950 border border-cyan-900/30 rounded-xl p-3 shadow-md">
              <div className="text-[10px] text-slate-500 font-bold">TOP OF CLIMB</div>
              <div className="text-xl font-bold text-indigo-300">
                {computedPlan.toc_nm.toFixed(0)}{' '}
                <span className="text-xs font-normal text-slate-400">NM</span>
              </div>
            </div>

            <div className="bg-slate-950 border border-cyan-900/30 rounded-xl p-3 shadow-md">
              <div className="text-[10px] text-slate-500 font-bold">TOP OF DESCENT</div>
              <div className="text-xl font-bold text-amber-300">
                {computedPlan.tod_nm.toFixed(0)}{' '}
                <span className="text-xs font-normal text-slate-400">NM</span>
              </div>
            </div>
          </div>

          {/* Vertical Profile Visualization */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-4 shadow-xl">
            <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
              <h3 className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
                <Compass className="w-4 h-4" />
                VERTICAL ALTITUDE PROFILE (FLIGHT PATH)
              </h3>
              <span className="text-[11px] text-slate-400">
                Cruise Level: FL{computedPlan.cruise_fl} ({computedPlan.cruise_fl * 100} FT)
              </span>
            </div>

            {/* SVG Profile Visualizer */}
            <div className="relative w-full h-36 bg-slate-900/80 rounded-lg p-2 border border-slate-800 overflow-hidden">
              <svg viewBox="0 0 500 120" className="w-full h-full preserve-3d" preserveAspectRatio="none">
                {/* Horizontal reference grid lines */}
                <line x1="0" y1="20" x2="500" y2="20" stroke="#334155" strokeDasharray="3 3" />
                <line x1="0" y1="60" x2="500" y2="60" stroke="#334155" strokeDasharray="3 3" />
                <line x1="0" y1="100" x2="500" y2="100" stroke="#334155" />

                {/* Profile line & area gradient */}
                <defs>
                  <linearGradient id="profileGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#0891b2" stopOpacity="0.0" />
                  </linearGradient>
                </defs>

                {/* Compute polygon points */}
                {(() => {
                  const totalDist = computedPlan.distance_nm || 1;
                  const maxAlt = Math.max(1000, computedPlan.cruise_fl * 100);
                  const pts = profileData.map(([d, a]) => {
                    const x = (d / totalDist) * 480 + 10;
                    const y = 100 - (a / maxAlt) * 80;
                    return `${x},${y}`;
                  });
                  const polyPoints = `10,100 ${pts.join(' ')} 490,100`;

                  return (
                    <>
                      <polygon points={polyPoints} fill="url(#profileGrad)" />
                      <polyline
                        points={pts.join(' ')}
                        fill="none"
                        stroke="#00e5ff"
                        strokeWidth="2.5"
                      />
                    </>
                  );
                })()}

                {/* Waypoint text labels */}
                <text x="15" y="115" fill="#10b981" fontSize="10" fontFamily="monospace">
                  {origin.icao} (0 NM)
                </text>
                <text x="440" y="115" fill="#f59e0b" fontSize="10" fontFamily="monospace">
                  {dest.icao}
                </text>
              </svg>
            </div>
          </div>

          {/* Fuel Estimates */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-4 shadow-xl">
            <div className="flex items-center justify-between mb-3 border-b border-slate-800 pb-2">
              <h3 className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
                <Fuel className="w-4 h-4 text-amber-400" />
                FUEL PLANNING ESTIMATE (ICAO/SIM APPROXIMATE)
              </h3>
              <span className="text-[11px] text-slate-500">Includes 45m Reserve & 5% Contingency</span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div className="bg-slate-900/70 p-2.5 rounded-lg border border-slate-800">
                <div className="text-[10px] text-slate-500">TRIP BURN</div>
                <div className="text-base font-bold text-slate-200">
                  {computedPlan.fuel_trip_kg.toFixed(0)} KG
                </div>
                <div className="text-[10px] text-slate-500">
                  {(computedPlan.fuel_trip_kg * 2.20462).toFixed(0)} LBS
                </div>
              </div>

              <div className="bg-slate-900/70 p-2.5 rounded-lg border border-slate-800">
                <div className="text-[10px] text-slate-500">RESERVE (45 MIN)</div>
                <div className="text-base font-bold text-slate-200">
                  {computedPlan.fuel_reserve_kg.toFixed(0)} KG
                </div>
                <div className="text-[10px] text-slate-500">
                  {(computedPlan.fuel_reserve_kg * 2.20462).toFixed(0)} LBS
                </div>
              </div>

              <div className="bg-slate-900/70 p-2.5 rounded-lg border border-slate-800">
                <div className="text-[10px] text-slate-500">CONTINGENCY (5%)</div>
                <div className="text-base font-bold text-slate-200">
                  {computedPlan.fuel_contingency_kg.toFixed(0)} KG
                </div>
                <div className="text-[10px] text-slate-500">
                  {(computedPlan.fuel_contingency_kg * 2.20462).toFixed(0)} LBS
                </div>
              </div>

              <div className="bg-slate-900/70 p-2.5 rounded-lg border border-cyan-800/50 bg-cyan-950/20">
                <div className="text-[10px] text-cyan-400 font-bold">TOTAL REQUIRED</div>
                <div className="text-base font-bold text-cyan-300">
                  {computedPlan.fuel_total_kg.toFixed(0)} KG
                </div>
                <div className="text-[10px] text-cyan-500">
                  {(computedPlan.fuel_total_kg * 2.20462).toFixed(0)} LBS
                </div>
              </div>
            </div>
          </div>

          {/* Live Weather & Aviation Data */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-4 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <h3 className="text-xs font-bold text-cyan-400 flex items-center gap-1.5">
                <Cloud className="w-4 h-4 text-cyan-300" />
                AVIATION WEATHER (METAR & TAF)
              </h3>
              <button
                onClick={fetchWeather}
                disabled={loadingWeather}
                className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-cyan-300 px-2 py-1 rounded bg-slate-900 border border-slate-800"
              >
                <RefreshCw className={`w-3 h-3 ${loadingWeather ? 'animate-spin' : ''}`} />
                <span>REFRESH</span>
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Origin Weather */}
              <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-emerald-400">{origin.icao} WEATHER</span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                      originMetar?.flight_category === 'VFR'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-600'
                        : originMetar?.flight_category === 'IFR'
                        ? 'bg-rose-950 text-rose-300 border border-rose-600'
                        : 'bg-amber-950 text-amber-300 border border-amber-600'
                    }`}
                  >
                    {originMetar?.flight_category || 'VFR'}
                  </span>
                </div>
                <div className="text-xs text-slate-300 font-mono break-all bg-slate-950/80 p-2 rounded border border-slate-800/80">
                  {rawOriginMetar || 'Fetching official AviationWeather METAR...'}
                </div>
                {originMetar && (
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 pt-1">
                    <div>
                      Wind:{' '}
                      <span className="text-slate-200 font-bold">
                        {originMetar.wind_dir ?? 'VRB'}° @ {originMetar.wind_kt ?? 0} KT
                        {originMetar.gust_kt ? ` G${originMetar.gust_kt}` : ''}
                      </span>
                    </div>
                    <div>
                      Altimeter:{' '}
                      <span className="text-slate-200 font-bold">
                        {originMetar.qnh_hpa ? `Q${originMetar.qnh_hpa}` : `${originMetar.altim_inhg}`}
                      </span>
                    </div>
                    <div>
                      Temp/Dew:{' '}
                      <span className="text-slate-200 font-bold">
                        {originMetar.temp_c}°C / {originMetar.dew_c}°C
                      </span>
                    </div>
                    <div>
                      Visibility:{' '}
                      <span className="text-slate-200 font-bold">{originMetar.vis || '10+ SM'}</span>
                    </div>
                  </div>
                )}
              </div>

              {/* Destination Weather */}
              <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-amber-400">{dest.icao} WEATHER</span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                      destMetar?.flight_category === 'VFR'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-600'
                        : destMetar?.flight_category === 'IFR'
                        ? 'bg-rose-950 text-rose-300 border border-rose-600'
                        : 'bg-amber-950 text-amber-300 border border-amber-600'
                    }`}
                  >
                    {destMetar?.flight_category || 'VFR'}
                  </span>
                </div>
                <div className="text-xs text-slate-300 font-mono break-all bg-slate-950/80 p-2 rounded border border-slate-800/80">
                  {rawDestMetar || 'Fetching official AviationWeather METAR...'}
                </div>
                {destMetar && (
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400 pt-1">
                    <div>
                      Wind:{' '}
                      <span className="text-slate-200 font-bold">
                        {destMetar.wind_dir ?? 'VRB'}° @ {destMetar.wind_kt ?? 0} KT
                      </span>
                    </div>
                    <div>
                      Altimeter:{' '}
                      <span className="text-slate-200 font-bold">
                        {destMetar.qnh_hpa ? `Q${destMetar.qnh_hpa}` : `${destMetar.altim_inhg}`}
                      </span>
                    </div>
                    <div>
                      Temp/Dew:{' '}
                      <span className="text-slate-200 font-bold">
                        {destMetar.temp_c}°C / {destMetar.dew_c}°C
                      </span>
                    </div>
                    <div>
                      Visibility:{' '}
                      <span className="text-slate-200 font-bold">{destMetar.vis || '10+ SM'}</span>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* SimBrief & External Tools bar */}
            <div className="pt-2 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="text-slate-400">SimBrief Import:</span>
                <input
                  type="text"
                  placeholder="Username / Pilot ID"
                  value={simbriefUser}
                  onChange={(e) => setSimbriefUser(e.target.value)}
                  className="bg-slate-900 border border-slate-700 px-2 py-1 rounded text-xs text-slate-200"
                />
                <button
                  onClick={handleImportSimbrief}
                  disabled={importingSimbrief}
                  className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700"
                >
                  {importingSimbrief ? 'FETCHING...' : 'FETCH OFP'}
                </button>
              </div>

              <a
                href="https://charts.navigraph.com"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 text-slate-400 hover:text-cyan-300 transition-colors"
              >
                <span>OPEN NAVIGRAPH CHARTS</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
