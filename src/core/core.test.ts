import test from 'node:test';
import assert from 'node:assert/strict';
import {
  distance_nm,
  bearing_deg,
  plan_flight,
  vertical_profile,
  decode_metar,
  export_gpx,
} from './plannerCore';
import { resolveAircraft } from '../data/aircraft';
import { lookupAirport } from '../data/airports';
import { ATCEngine, normalize, contains_token } from './atcEngine';
import { TelemetryParser } from './telemetryParser';
import { FlightMonitor } from './flightMonitor';
import { CHECKLISTS } from '../data/checklists';

test('distance calculation JFK to LHR', () => {
  const d = distance_nm(40.6398, -73.7789, 51.47, -0.4543);
  assert.ok(d > 2990 && d < 3040, `Distance was ${d}`);
});

test('bearing calculation', () => {
  const brg = bearing_deg(0, 0, 1, 0); // straight North
  assert.ok(Math.abs(brg - 0) < 0.1 || Math.abs(brg - 360) < 0.1, `Bearing was ${brg}`);
  const brgEast = bearing_deg(0, 0, 0, 1); // straight East
  assert.ok(Math.abs(brgEast - 90) < 0.1, `Bearing East was ${brgEast}`);
});

test('plan long and short routes', () => {
  const jfk = lookupAirport('KJFK')!;
  const lhr = lookupAirport('EGLL')!;
  assert.ok(jfk && lhr);

  const plan = plan_flight(
    [
      [jfk.lat, jfk.lon],
      [lhr.lat, lhr.lon],
    ],
    'B77W',
    370
  );
  assert.equal(plan.cruise_fl, 370);
  assert.ok(plan.toc_nm < plan.tod_nm);
  assert.ok(plan.ete_min > 340 && plan.ete_min < 420, `ETE was ${plan.ete_min}`);
  assert.ok(plan.fuel_total_kg > plan.fuel_trip_kg && plan.fuel_trip_kg > 0);

  // Short hop: cruise level must shrink so climb + descent fit
  const shortPlan = plan_flight(
    [
      [0.0, 0.0],
      [0.0, 2.0],
    ],
    'A320',
    380
  );
  assert.ok(shortPlan.cruise_fl < 380);
  assert.ok(shortPlan.toc_nm <= shortPlan.tod_nm + 1e-4);

  const prof = vertical_profile(shortPlan);
  assert.equal(prof[0][1], 0);
  assert.equal(prof[prof.length - 1][1], 0);
});

test('plan speed override', () => {
  const points: Array<[number, number]> = [
    [40.6413, -73.7781],
    [51.47, -0.4543],
  ];
  const nominal = plan_flight(points, 'A320', 360);
  const faster = plan_flight(points, 'A320', 360, 45, 0.05, 500);

  assert.equal(faster.tas_kt, 500);
  assert.ok(faster.ete_min < nominal.ete_min);

  const ignored = plan_flight(points, 'A320', 360, 45, 0.05, 9999);
  assert.equal(ignored.tas_kt, nominal.tas_kt);
});

test('aircraft resolution and aliases', () => {
  assert.equal(resolveAircraft('Airbus A350-1000 XWB'), 'A35K');
  assert.equal(resolveAircraft('zzz'), 'A320');
  assert.equal(resolveAircraft('B737'), 'B738');
  assert.equal(resolveAircraft('Learjet 45'), 'LJ45');
});

test('METAR decoder', () => {
  const m = decode_metar('METAR KJFK 011251Z 24008G15KT 10SM FEW050 20/12 A3010');
  assert.equal(m.wind_dir, 240);
  assert.equal(m.wind_kt, 8);
  assert.equal(m.gust_kt, 15);
  assert.equal(m.vis, '10 SM');
  assert.equal(m.temp_c, 20);
  assert.equal(m.dew_c, 12);
  assert.equal(m.altim_inhg, 30.1);
  assert.equal(m.time_z, '1251Z');

  const q = decode_metar('EGLL 011250Z 27012KT 9999 M02/M05 Q1021');
  assert.equal(q.qnh_hpa, 1021);
  assert.equal(q.temp_c, -2);
  assert.equal(q.vis, '10 KM');
});

test('GPX export format', () => {
  const gpx = export_gpx('T', [
    ['KJFK', 40.6, -73.7],
    ['EGLL', 51.4, -0.4],
  ]);
  assert.ok(gpx.includes('KJFK') && gpx.includes('EGLL'));
  assert.ok(gpx.includes('<rtept lat="40.600000" lon="-73.700000">'));
});

test('normalize text and tokens', () => {
  assert.ok(contains_token(normalize('runway two eight left'), '28L'));
  assert.ok(contains_token(normalize('squawk four five two one'), '4521'));
  assert.ok(contains_token(normalize('climb and maintain five thousand'), '5000'));
  assert.ok(contains_token(normalize('expect flight level three six zero'), 'FL360'));
  assert.ok(!contains_token(normalize('squawk 14521'), '4521'));
});

test('ATC conversation flow', () => {
  const e = new ATCEngine();
  e.set_callsign('UGA101');
  e.set_plan('HUEN', 'HKJK', 360);
  e.set_metar('HUEN', 'HUEN 011251Z 12008KT 9999 24/18 Q1019');
  e.set_runways('HUEN', ['17', '35']);
  e.set_runways('HKJK', ['06', '24']);

  const r1 = e.handle('request IFR clearance');
  assert.ok(r1.includes('cleared to HKJK') && r1.includes('Squawk'), r1);
  const sq = e.squawk!;
  assert.ok(sq && sq.length === 4);

  // Incomplete readback should be rejected
  const neg = e.handle('roger');
  assert.ok(neg.includes('negative'), neg);

  // Proper readback accepted
  const ok = e.handle(`climb and maintain five thousand squawk ${sq.split('').join(' ')}`);
  assert.ok(ok.includes('readback correct'), ok);

  // Taxi request with wind 120 favouring 17 over 35
  const taxi = e.handle('request taxi');
  assert.ok(taxi.includes('runway 17') && taxi.includes('QNH 1019'), taxi);

  assert.ok(e.handle('taxi runway one seven hold short').includes('readback correct'));
  assert.ok(e.handle('ready for departure').includes('cleared for takeoff'));

  e.handle('inbound HKJK');
  const far = { lat: 0.04, lon: 32.44 };
  assert.ok(e.handle('request landing', far).includes('continue approach'));
  const near = { lat: -1.3, lon: 36.9 };
  assert.ok(e.handle('request landing', near).includes('cleared to land'));
});

test('ATC emergency and direct routing', () => {
  const e = new ATCEngine();
  e.set_callsign('AAL442');
  e.set_plan('KJFK', 'KLAX', 380);

  const mayday = e.handle('MAYDAY MAYDAY engine fire');
  assert.ok(mayday.includes('roger mayday') && mayday.includes('souls on board'), mayday);

  const dir = e.handle('direct KSFO', { lat: 37.0, lon: -121.0 });
  assert.ok(dir.includes('proceed direct KSFO') && dir.includes('Bearing'), dir);
});

test('telemetry parsing XGPS and XATT', () => {
  const parser = new TelemetryParser();
  const chunk =
    'XGPSAerofly FS Global,32.4435,0.0424,1000,90,50 XATTAerofly FS Global,91,2.5,-1.2 ';
  const remaining = parser.consumeBuffer('', chunk, '192.168.1.10');
  assert.equal(remaining, '');

  const snap = parser.getSnapshot();
  assert.equal(snap.packets, 2);
  assert.ok(Math.abs(snap.lon! - 32.4435) < 1e-4);
  assert.ok(Math.abs(snap.lat! - 0.0424) < 1e-4);
  assert.equal(snap.heading, 91);
  assert.equal(snap.pitch, 2.5);
  assert.equal(snap.roll, -1.2);
  assert.ok(snap.alt > 3200 && snap.alt < 3300); // 1000m to ft
  assert.ok(snap.speed > 95 && snap.speed < 100); // 50 mps to kt
});

test('flight monitor events and automatic logbook', () => {
  const monitor = new FlightMonitor();
  monitor.set_plan('HUEN', 'HKJK', [-1.3192, 36.9278], 120.0);

  const snap = (lat: number, lon: number, gs: number, alt: number) => ({
    connected: true,
    lat,
    lon,
    speed_kt: gs,
    alt_ft: alt,
  });

  // Parked
  assert.deepEqual(monitor.update(snap(0.04, 32.44, 0, 3800), 0), []);
  // Rolling
  assert.deepEqual(monitor.update(snap(0.04, 32.44, 80, 3850), 10000), []);
  // Takeoff
  assert.deepEqual(monitor.update(snap(0.05, 32.5, 150, 4200), 20000), ['takeoff']);
  // Cruise
  assert.deepEqual(monitor.update(snap(-0.5, 34.5, 450, 36000), 2000000), []);
  // Top of Descent (~70 NM out <= 120 NM)
  assert.deepEqual(monitor.update(snap(-1.0, 35.8, 450, 36000), 2600000), ['top_of_descent']);
  // Approach
  assert.deepEqual(monitor.update(snap(-1.28, 36.85, 250, 6000), 3000000), ['approach']);
  // Landing
  assert.deepEqual(monitor.update(snap(-1.3192, 36.9278, 20, 5400), 3300000), ['landing']);

  const logs = monitor.getLogbook();
  assert.equal(logs.length, 1);
  assert.equal(logs[0].origin, 'HUEN');
  assert.equal(logs[0].dest, 'HKJK');
  assert.ok(logs[0].nm > 100);
  assert.ok(logs[0].max_alt >= 36000);
  assert.equal(Object.keys(CHECKLISTS).length, 9);
});
