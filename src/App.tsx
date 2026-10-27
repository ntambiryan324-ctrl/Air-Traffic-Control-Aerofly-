import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Navbar } from './components/Navbar';
import { QuickHUD } from './components/QuickHUD';
import { RadarMap } from './components/RadarMap';
import { FlightPlanner } from './components/FlightPlanner';
import { ATCComms } from './components/ATCComms';
import { FlightTools } from './components/FlightTools';
import { TelemetryLink } from './components/TelemetryLink';
import { Airport, DecodedMetar, FlightPlan, LogbookEntry, TelemetryData } from './types/aviation';
import { AIRPORTS } from './data/airports';
import { ATCEngine } from './core/atcEngine';
import { TelemetryParser } from './core/telemetryParser';
import { FlightMonitor } from './core/flightMonitor';
import { telemetrySimulator } from './services/telemetrySimulator';
import { audioSynthesizer } from './services/audioSynthesizer';
import { decode_metar } from './core/plannerCore';

export default function App() {
  const [activeTab, setActiveTab] = useState<'GLOBE' | 'PLAN' | 'ATC' | 'TOOLS' | 'LINK'>('GLOBE');
  const [callsign, setCallsign] = useState('UGA101');
  const [origin, setOrigin] = useState<Airport>(AIRPORTS.HUEN);
  const [dest, setDest] = useState<Airport>(AIRPORTS.HKJK);
  const [flightPlan, setFlightPlan] = useState<FlightPlan | null>(null);
  const [originMetar, setOriginMetar] = useState<DecodedMetar | null>(null);

  const [telemetry, setTelemetry] = useState<TelemetryData>({
    connected: false,
    transport: 'WAITING',
    lat: 0.0424,
    lon: 32.4435,
    alt: 3782,
    speed: 0,
    heading: 170,
    pitch: 0,
    roll: 0,
    vs: 0,
    packets: 0,
    message: 'Aerofly Air Control ready. Connect to Aerofly FS Global or start demo flight.',
    last: Date.now(),
  });

  const [isSimRunning, setIsSimRunning] = useState(false);
  const [simMultiplier, setSimMultiplier] = useState(1);
  const [logbook, setLogbook] = useState<LogbookEntry[]>([
    {
      id: 'init-log-1',
      date: '2026-10-26',
      origin: 'HUEN',
      dest: 'HKJK',
      aircraft: 'A320',
      minutes: 68,
      nm: 312,
      max_alt: 36000,
    },
  ]);

  // Persistent instances
  const atcEngineRef = useRef<ATCEngine>(new ATCEngine());
  const telemetryParserRef = useRef<TelemetryParser>(new TelemetryParser());
  const flightMonitorRef = useRef<FlightMonitor>(new FlightMonitor(logbook));

  // Initialize ATC Engine & Flight Monitor with initial plan
  useEffect(() => {
    const atc = atcEngineRef.current;
    atc.set_callsign(callsign);
    atc.set_plan(origin.icao, dest.icao, 360);
    if (origin.runways) atc.set_runways(origin.icao, origin.runways);
    if (dest.runways) atc.set_runways(dest.icao, dest.runways);

    flightMonitorRef.current.set_plan(
      origin.icao,
      dest.icao,
      [dest.lat, dest.lon],
      120.0
    );

    // Initialize telemetry simulator
    telemetrySimulator.init(origin, dest, flightPlan, (data) => {
      setTelemetry(data);
      handleTelemetryTick(data);
    });

    // Check ?autostart=1 query param
    if (typeof window !== 'undefined') {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('autostart') === '1') {
        handleToggleSim();
      }
    }
  }, []);

  // Update telemetry simulator and monitor when origin/dest changes
  useEffect(() => {
    const atc = atcEngineRef.current;
    atc.set_plan(origin.icao, dest.icao, flightPlan?.cruise_fl || 360);
    if (origin.runways) atc.set_runways(origin.icao, origin.runways);
    if (dest.runways) atc.set_runways(dest.icao, dest.runways);

    flightMonitorRef.current.set_plan(
      origin.icao,
      dest.icao,
      [dest.lat, dest.lon],
      flightPlan?.tod_nm ? flightPlan.distance_nm - flightPlan.tod_nm : 120.0
    );

    telemetrySimulator.init(origin, dest, flightPlan, (data) => {
      setTelemetry(data);
      handleTelemetryTick(data);
    });
  }, [origin, dest, flightPlan]);

  // Handle proactive flight monitor events on telemetry updates
  const handleTelemetryTick = (data: TelemetryData) => {
    if (!data.connected || data.lat === null || data.lon === null) return;

    const events = flightMonitorRef.current.update({
      connected: data.connected,
      lat: data.lat,
      lon: data.lon,
      speed_kt: data.speed,
      alt_ft: data.alt,
    });

    if (events.length > 0) {
      setLogbook(flightMonitorRef.current.getLogbook());

      events.forEach((ev) => {
        const atcCallout = atcEngineRef.current.event(ev);
        if (atcCallout) {
          audioSynthesizer.speakATC(atcCallout);
        }
      });
    }
  };

  const handleApplyPlan = (newPlan: FlightPlan, metarRaw?: string) => {
    setFlightPlan(newPlan);
    if (metarRaw) {
      atcEngineRef.current.set_metar(newPlan.origin, metarRaw);
      setOriginMetar(decode_metar(metarRaw));
    }
    atcEngineRef.current.set_plan(newPlan.origin, newPlan.dest, newPlan.cruise_fl);
  };

  const handleToggleSim = () => {
    if (isSimRunning) {
      telemetrySimulator.stop();
      setIsSimRunning(false);
    } else {
      telemetrySimulator.start((data) => {
        setTelemetry(data);
        handleTelemetryTick(data);
      });
      setIsSimRunning(true);
    }
  };

  const handleCycleMultiplier = () => {
    const next = simMultiplier === 1 ? 2 : simMultiplier === 2 ? 5 : simMultiplier === 5 ? 10 : 1;
    setSimMultiplier(next);
    telemetrySimulator.setSpeedMultiplier(next);
  };

  const handleSetMultiplier = (m: number) => {
    setSimMultiplier(m);
    telemetrySimulator.setSpeedMultiplier(m);
  };

  const handleResetSim = () => {
    telemetrySimulator.jumpToPhase('PARKED');
    flightMonitorRef.current.reset_flight();
  };

  const handleJumpPhase = (phase: 'PARKED' | 'TAKEOFF' | 'CRUISE' | 'DESCENT' | 'FINAL') => {
    telemetrySimulator.jumpToPhase(phase);
  };

  const handleInjectPacket = (raw: string) => {
    telemetryParserRef.current.consumeBuffer('', raw, 'Manual Injection');
    const snap = telemetryParserRef.current.getSnapshot();
    setTelemetry(snap);
    handleTelemetryTick(snap);
  };

  const handleAddLog = (entry: Omit<LogbookEntry, 'id'>) => {
    const newEntry = flightMonitorRef.current.addManualEntry(entry);
    setLogbook(flightMonitorRef.current.getLogbook());
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-mono selection:bg-cyan-500 selection:text-white">
      {/* Top Avionics Navigation */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        telemetry={telemetry}
        isSimRunning={isSimRunning}
        onToggleSim={handleToggleSim}
        simMultiplier={simMultiplier}
        onCycleMultiplier={handleCycleMultiplier}
        onResetSim={handleResetSim}
        callsign={callsign}
      />

      {/* Main Tab Views */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-3 sm:p-5 space-y-4">
        {/* Quick HUD docked on top */}
        <QuickHUD
          telemetry={telemetry}
          targetAlt={flightPlan?.cruise_fl ? flightPlan.cruise_fl * 100 : 36000}
          squawk={atcEngineRef.current.squawk || '1200'}
        />

        {/* Tab 1: GLOBE / RADAR MAP */}
        {activeTab === 'GLOBE' && (
          <RadarMap
            telemetry={telemetry}
            origin={origin}
            dest={dest}
            flightPlan={flightPlan}
          />
        )}

        {/* Tab 2: PLAN / FLIGHT PLANNING */}
        {activeTab === 'PLAN' && (
          <FlightPlanner
            origin={origin}
            dest={dest}
            onSetOrigin={setOrigin}
            onSetDest={setDest}
            flightPlan={flightPlan}
            onApplyPlan={handleApplyPlan}
          />
        )}

        {/* Tab 3: ATC / COMMUNICATIONS */}
        {activeTab === 'ATC' && (
          <ATCComms
            atcEngine={atcEngineRef.current}
            callsign={callsign}
            origin={origin}
            dest={dest}
            telemetry={telemetry}
            originMetar={originMetar}
          />
        )}

        {/* Tab 4: TOOLS / EFB APPS */}
        {activeTab === 'TOOLS' && (
          <FlightTools
            logbook={logbook}
            onAddLog={handleAddLog}
            activeRunway={atcEngineRef.current.dep_runway || origin.runways?.[0] || '17'}
          />
        )}

        {/* Tab 5: LINK / SIMULATOR CONNECTION */}
        {activeTab === 'LINK' && (
          <TelemetryLink
            telemetry={telemetry}
            isSimRunning={isSimRunning}
            onToggleSim={handleToggleSim}
            simMultiplier={simMultiplier}
            onSetMultiplier={handleSetMultiplier}
            onResetSim={handleResetSim}
            onJumpPhase={handleJumpPhase}
            onInjectPacket={handleInjectPacket}
          />
        )}
      </main>

      {/* Bottom Footer Info */}
      <footer className="border-t border-slate-900 bg-slate-950 py-3 text-center text-xs text-slate-500 font-mono">
        <p>
          Aerofly Air Control • EFB Companion for Aerofly FS Global • For Flight Simulation Use Only
        </p>
      </footer>
    </div>
  );
}
