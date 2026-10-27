import React, { useState } from 'react';
import { CHECKLISTS } from '../data/checklists';
import { LogbookEntry } from '../types/aviation';
import {
  CheckSquare,
  BookOpen,
  Edit3,
  Calculator,
  RotateCcw,
  Download,
  Plus,
  Compass,
  Wind,
} from 'lucide-react';

interface FlightToolsProps {
  logbook: LogbookEntry[];
  onAddLog: (entry: Omit<LogbookEntry, 'id'>) => void;
  activeRunway?: string;
}

export const FlightTools: React.FC<FlightToolsProps> = ({
  logbook,
  onAddLog,
  activeRunway = '17',
}) => {
  const [activeSubTab, setActiveSubTab] = useState<
    'CHECKLISTS' | 'LOGBOOK' | 'SCRATCHPAD' | 'CALCULATOR' | 'GLOSSARY'
  >('CHECKLISTS');

  // Checklists State
  const [selectedPhase, setSelectedPhase] = useState<string>('BEFORE START');
  const [checkedItems, setCheckedItems] = useState<Record<string, boolean>>({});

  // Scratchpad State
  const [scratchpadText, setScratchpadText] = useState(
    'CLEARANCE:\nRUNWAY:\nATIS:\nSQUAWK:\nALTITUDE:\nREMARKS:'
  );

  // Converters State
  const [inhg, setInhg] = useState<string>('29.92');
  const [hpa, setHpa] = useState<string>('1013');
  const [feet, setFeet] = useState<string>('36000');
  const [meters, setMeters] = useState<string>('10973');
  const [kg, setKg] = useState<string>('10000');
  const [lbs, setLbs] = useState<string>('22046');

  // Crosswind Calculator State
  const [rwyHdg, setRwyHdg] = useState<number>(170);
  const [windDir, setWindDir] = useState<number>(120);
  const [windSpd, setWindSpd] = useState<number>(15);

  // Manual Log Dialog State
  const [showAddLogModal, setShowAddLogModal] = useState(false);
  const [manualOrig, setManualOrig] = useState('HUEN');
  const [manualDest, setManualDest] = useState('HKJK');
  const [manualTime, setManualTime] = useState('65');
  const [manualNm, setManualNm] = useState('310');
  const [manualAlt, setManualAlt] = useState('36000');

  // Crosswind math
  const angleDiff = ((windDir - rwyHdg + 180 + 360) % 360) - 180;
  const rad = (angleDiff * Math.PI) / 180;
  const headwind = Math.round(windSpd * Math.cos(rad));
  const crosswind = Math.round(windSpd * Math.sin(rad));

  const toggleCheck = (item: string) => {
    setCheckedItems((prev) => ({ ...prev, [item]: !prev[item] }));
  };

  const resetCurrentChecklist = () => {
    const items = CHECKLISTS[selectedPhase] || [];
    setCheckedItems((prev) => {
      const next = { ...prev };
      items.forEach((it) => delete next[it]);
      return next;
    });
  };

  const handleExportLogbook = () => {
    const jsonStr = JSON.stringify(logbook, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `aerofly_logbook_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveManualLog = (e: React.FormEvent) => {
    e.preventDefault();
    onAddLog({
      date: new Date().toISOString().split('T')[0],
      origin: manualOrig.toUpperCase(),
      dest: manualDest.toUpperCase(),
      aircraft: 'A320',
      minutes: parseInt(manualTime, 10) || 60,
      nm: parseInt(manualNm, 10) || 300,
      max_alt: parseInt(manualAlt, 10) || 36000,
    });
    setShowAddLogModal(false);
  };

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-6 text-slate-100 font-mono select-none">
      {/* Sub-navigation */}
      <div className="flex space-x-2 border-b border-slate-800 pb-2 overflow-x-auto">
        {[
          { id: 'CHECKLISTS', label: 'FLIGHT CHECKLISTS', icon: CheckSquare },
          { id: 'LOGBOOK', label: 'PILOT LOGBOOK', icon: BookOpen },
          { id: 'SCRATCHPAD', label: 'COCKPIT SCRATCHPAD', icon: Edit3 },
          { id: 'CALCULATOR', label: 'AVIONICS CONVERTERS', icon: Calculator },
          { id: 'GLOSSARY', label: 'FAA GLOSSARY', icon: Compass },
        ].map((t) => {
          const Icon = t.icon;
          const isActive = activeSubTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveSubTab(t.id as any)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-bold transition-all ${
                isActive
                  ? 'bg-cyan-950 text-cyan-300 border border-cyan-500/50 shadow-sm'
                  : 'bg-slate-900/60 text-slate-400 hover:text-slate-200 hover:bg-slate-900'
              }`}
            >
              <Icon className={`w-4 h-4 ${isActive ? 'text-cyan-400' : 'text-slate-500'}`} />
              <span>{t.label}</span>
            </button>
          );
        })}
      </div>

      {/* CHECKLISTS TAB */}
      {activeSubTab === 'CHECKLISTS' && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {/* Phase Selector Column */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-3 shadow-xl space-y-1">
            <div className="text-[10px] text-slate-500 font-bold px-3 py-1 uppercase">
              Standard Flight Phases
            </div>
            {Object.keys(CHECKLISTS).map((phase) => {
              const items = CHECKLISTS[phase];
              const completedCount = items.filter((it) => checkedItems[it]).length;
              const isAllDone = completedCount === items.length;
              const isCurrent = selectedPhase === phase;

              return (
                <button
                  key={phase}
                  onClick={() => setSelectedPhase(phase)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-xs font-bold flex items-center justify-between transition-colors ${
                    isCurrent
                      ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-600'
                      : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  <span>{phase}</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      isAllDone
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-600'
                        : completedCount > 0
                        ? 'bg-cyan-950 text-cyan-400'
                        : 'bg-slate-900 text-slate-500'
                    }`}
                  >
                    {completedCount}/{items.length}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Checklist Items Column */}
          <div className="md:col-span-3 bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="text-base font-bold text-cyan-300">{selectedPhase} CHECKLIST</h3>
                <p className="text-xs text-slate-400">
                  Verify each item in standard crew challenge and response protocol
                </p>
              </div>
              <button
                onClick={resetCurrentChecklist}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-cyan-300 bg-slate-900 border border-slate-800"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>RESET PHASE</span>
              </button>
            </div>

            <div className="space-y-2">
              {(CHECKLISTS[selectedPhase] || []).map((item) => {
                const isChecked = !!checkedItems[item];
                return (
                  <div
                    key={item}
                    onClick={() => toggleCheck(item)}
                    className={`p-3 rounded-lg border flex items-center justify-between cursor-pointer transition-all ${
                      isChecked
                        ? 'bg-emerald-950/40 border-emerald-600/50 text-emerald-200'
                        : 'bg-slate-900/80 border-slate-800 text-slate-200 hover:border-slate-700'
                    }`}
                  >
                    <span className="text-sm font-semibold">{item}</span>
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => {}}
                      className="w-4 h-4 accent-emerald-500 rounded cursor-pointer"
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* LOGBOOK TAB */}
      {activeSubTab === 'LOGBOOK' && (
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
            <div>
              <h3 className="text-base font-bold text-cyan-300">AUTOMATIC PILOT LOGBOOK</h3>
              <p className="text-xs text-slate-400">
                Flights are automatically logged from takeoff to landing with nautical miles and max FL
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowAddLogModal(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-bold transition-all shadow"
              >
                <Plus className="w-4 h-4" />
                <span>ADD MANUAL FLIGHT</span>
              </button>
              <button
                onClick={handleExportLogbook}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-xs text-slate-300"
              >
                <Download className="w-3.5 h-3.5" />
                <span>EXPORT JSON</span>
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-900 text-slate-400 uppercase text-[10px]">
                <tr>
                  <th className="p-3">DATE</th>
                  <th className="p-3">ROUTE</th>
                  <th className="p-3">AIRCRAFT</th>
                  <th className="p-3">DURATION</th>
                  <th className="p-3">DISTANCE</th>
                  <th className="p-3">MAX ALTITUDE</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {logbook.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="p-6 text-center text-slate-500 italic">
                      No flights logged yet. Start a flight simulation or connect Aerofly FS Global.
                    </td>
                  </tr>
                ) : (
                  logbook.map((log) => (
                    <tr key={log.id} className="hover:bg-slate-900/50">
                      <td className="p-3 text-slate-300">{log.date}</td>
                      <td className="p-3 font-bold text-cyan-300">
                        {log.origin} → {log.dest}
                      </td>
                      <td className="p-3 text-slate-300">{log.aircraft}</td>
                      <td className="p-3 text-emerald-400 font-bold">
                        {Math.floor(log.minutes / 60)}h {(log.minutes % 60).toString().padStart(2, '0')}m
                      </td>
                      <td className="p-3 text-slate-300">{log.nm} NM</td>
                      <td className="p-3 text-amber-300 font-bold">
                        {log.max_alt.toLocaleString()} FT (FL{Math.round(log.max_alt / 100)})
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* SCRATCHPAD TAB */}
      {activeSubTab === 'SCRATCHPAD' && (
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <div>
              <h3 className="text-base font-bold text-cyan-300">PILOT COCKPIT SCRATCHPAD</h3>
              <p className="text-xs text-slate-400">
                Quick handwritten note area for clearances, transponder squawks, frequencies, and ATC taxi instructions
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() =>
                  setScratchpadText((p) => p + `\nRWY ${activeRunway} IN USE`)
                }
                className="px-2.5 py-1 rounded bg-slate-900 text-xs text-slate-300 border border-slate-700"
              >
                + Active RWY
              </button>
              <button
                onClick={() =>
                  setScratchpadText('CLEARANCE:\nRUNWAY:\nATIS:\nSQUAWK:\nALTITUDE:\nREMARKS:')
                }
                className="px-2.5 py-1 rounded bg-slate-900 text-xs text-slate-400 border border-slate-800"
              >
                Reset Template
              </button>
            </div>
          </div>

          <textarea
            value={scratchpadText}
            onChange={(e) => setScratchpadText(e.target.value)}
            rows={12}
            className="w-full bg-slate-900/90 border border-slate-700 rounded-lg p-4 font-mono text-sm text-cyan-300 focus:outline-none focus:border-cyan-500 leading-relaxed"
          />
        </div>
      )}

      {/* CALCULATORS TAB */}
      {activeSubTab === 'CALCULATOR' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Crosswind Calculator */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
            <h3 className="text-sm font-bold text-cyan-300 flex items-center gap-2 border-b border-slate-800 pb-2">
              <Wind className="w-4 h-4 text-cyan-400" />
              RUNWAY CROSSWIND & HEADWIND COMPONENT
            </h3>

            <div className="grid grid-cols-3 gap-3 text-xs">
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">RUNWAY HEADING (°)</label>
                <input
                  type="number"
                  value={rwyHdg}
                  onChange={(e) => setRwyHdg(parseInt(e.target.value, 10) || 0)}
                  className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-200"
                />
              </div>

              <div>
                <label className="text-[11px] text-slate-400 block mb-1">WIND DIRECTION (°)</label>
                <input
                  type="number"
                  value={windDir}
                  onChange={(e) => setWindDir(parseInt(e.target.value, 10) || 0)}
                  className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-200"
                />
              </div>

              <div>
                <label className="text-[11px] text-slate-400 block mb-1">WIND SPEED (KT)</label>
                <input
                  type="number"
                  value={windSpd}
                  onChange={(e) => setWindSpd(parseInt(e.target.value, 10) || 0)}
                  className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-200"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2">
              <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 text-center">
                <div className="text-xs text-slate-400">
                  {headwind >= 0 ? 'HEADWIND COMPONENT' : 'TAILWIND COMPONENT'}
                </div>
                <div
                  className={`text-2xl font-bold mt-1 ${
                    headwind >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {Math.abs(headwind)} KT
                </div>
              </div>

              <div className="bg-slate-900 p-4 rounded-xl border border-slate-800 text-center">
                <div className="text-xs text-slate-400">CROSSWIND COMPONENT</div>
                <div
                  className={`text-2xl font-bold mt-1 ${
                    Math.abs(crosswind) > 25
                      ? 'text-rose-400'
                      : Math.abs(crosswind) > 15
                      ? 'text-amber-400'
                      : 'text-cyan-400'
                  }`}
                >
                  {Math.abs(crosswind)} KT {crosswind > 0 ? '(FROM RIGHT)' : crosswind < 0 ? '(FROM LEFT)' : ''}
                </div>
              </div>
            </div>
          </div>

          {/* Unit Converters */}
          <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
            <h3 className="text-sm font-bold text-cyan-300 flex items-center gap-2 border-b border-slate-800 pb-2">
              <Calculator className="w-4 h-4 text-cyan-400" />
              AVIONICS CONVERTERS
            </h3>

            {/* QNH / Altimeter */}
            <div className="space-y-1">
              <div className="text-xs text-slate-400 font-bold">ALTIMETER / BARO (inHg ⇄ hPa)</div>
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="number"
                  step="0.01"
                  value={inhg}
                  onChange={(e) => {
                    const v = e.target.value;
                    setInhg(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setHpa(Math.round(n / 0.02953).toString());
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-cyan-300"
                  placeholder="inHg (29.92)"
                />
                <input
                  type="number"
                  value={hpa}
                  onChange={(e) => {
                    const v = e.target.value;
                    setHpa(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setInhg((n * 0.02953).toFixed(2));
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-emerald-300"
                  placeholder="hPa (1013)"
                />
              </div>
            </div>

            {/* Altitude Feet <-> Meters */}
            <div className="space-y-1 pt-2 border-t border-slate-900">
              <div className="text-xs text-slate-400 font-bold">ALTITUDE (Feet ⇄ Meters)</div>
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="number"
                  value={feet}
                  onChange={(e) => {
                    const v = e.target.value;
                    setFeet(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setMeters(Math.round(n * 0.3048).toString());
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-cyan-300"
                  placeholder="Feet"
                />
                <input
                  type="number"
                  value={meters}
                  onChange={(e) => {
                    const v = e.target.value;
                    setMeters(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setFeet(Math.round(n / 0.3048).toString());
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-emerald-300"
                  placeholder="Meters"
                />
              </div>
            </div>

            {/* Fuel KG <-> LBS */}
            <div className="space-y-1 pt-2 border-t border-slate-900">
              <div className="text-xs text-slate-400 font-bold">FUEL MASS (Kilograms ⇄ Pounds)</div>
              <div className="grid grid-cols-2 gap-3">
                <input
                  type="number"
                  value={kg}
                  onChange={(e) => {
                    const v = e.target.value;
                    setKg(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setLbs(Math.round(n * 2.20462).toString());
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-cyan-300"
                  placeholder="Kilograms"
                />
                <input
                  type="number"
                  value={lbs}
                  onChange={(e) => {
                    const v = e.target.value;
                    setLbs(v);
                    const n = parseFloat(v);
                    if (!isNaN(n)) setKg(Math.round(n / 2.20462).toString());
                  }}
                  className="bg-slate-900 border border-slate-700 p-2 rounded text-xs text-emerald-300"
                  placeholder="Pounds"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* FAA GLOSSARY TAB */}
      {activeSubTab === 'GLOSSARY' && (
        <div className="bg-slate-950 border border-cyan-900/40 rounded-xl p-5 shadow-xl space-y-4">
          <h3 className="text-base font-bold text-cyan-300 border-b border-slate-800 pb-2">
            FAA & ICAO PILOT/CONTROLLER GLOSSARY
          </h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">CLEARED AS FILED:</span>
              <p className="text-slate-300 mt-1">
                Means the aircraft is cleared to proceed in accordance with the route of flight filed in the flight plan.
              </p>
            </div>
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">HOLD SHORT:</span>
              <p className="text-slate-300 mt-1">
                Instructions to stop and hold at a designated point, usually runway holding position markings. Mandatory readback required.
              </p>
            </div>
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">RADAR CONTACT:</span>
              <p className="text-slate-300 mt-1">
                The situation when radar identification of a particular aircraft is established and radar services are being provided.
              </p>
            </div>
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">DIRECT TO:</span>
              <p className="text-slate-300 mt-1">
                Authorization to fly directly towards a fix or waypoint rather than following airway radials.
              </p>
            </div>
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">TOP OF DESCENT (TOD):</span>
              <p className="text-slate-300 mt-1">
                The computed point at which an aircraft transitions from cruise flight to descent towards the destination.
              </p>
            </div>
            <div className="bg-slate-900/70 p-3 rounded-lg border border-slate-800">
              <span className="font-bold text-cyan-400">SQUAWK IDENT:</span>
              <p className="text-slate-300 mt-1">
                Activate the 'IDENT' feature on the aircraft transponder to highlight the radar return on the controller's screen.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Manual Flight Log Dialog */}
      {showAddLogModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-slate-950 border border-cyan-800 rounded-xl p-5 w-full max-w-md shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-cyan-300">ADD MANUAL FLIGHT LOG</h3>
            <form onSubmit={handleSaveManualLog} className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">ORIGIN ICAO</label>
                  <input
                    type="text"
                    value={manualOrig}
                    onChange={(e) => setManualOrig(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-100 uppercase"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">DEST ICAO</label>
                  <input
                    type="text"
                    value={manualDest}
                    onChange={(e) => setManualDest(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-100 uppercase"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">TIME (MIN)</label>
                  <input
                    type="number"
                    value={manualTime}
                    onChange={(e) => setManualTime(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">DIST (NM)</label>
                  <input
                    type="number"
                    value={manualNm}
                    onChange={(e) => setManualNm(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-100"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">MAX ALT (FT)</label>
                  <input
                    type="number"
                    value={manualAlt}
                    onChange={(e) => setManualAlt(e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 p-2 rounded text-slate-100"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3">
                <button
                  type="button"
                  onClick={() => setShowAddLogModal(false)}
                  className="px-3 py-1.5 rounded bg-slate-800 text-slate-300"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-white font-bold"
                >
                  Save Log Entry
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
