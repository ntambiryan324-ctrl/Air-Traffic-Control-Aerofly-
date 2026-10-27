import { Airport, FlightPlan, TelemetryData } from '../types/aviation';
import { bearing_deg, distance_nm } from '../core/plannerCore';

export class TelemetrySimulator {
  private active = false;
  private timer: any = null;
  private currentLat = 0.0424;
  private currentLon = 32.4435;
  private currentAlt = 3782;
  private currentHdg = 170;
  private currentSpeed = 0;
  private currentPitch = 0;
  private currentRoll = 0;
  private currentVs = 0;
  private simSpeedMultiplier = 1;
  private phaseIndex = 0;

  private routeWaypoints: Array<{ lat: number; lon: number; name: string }> = [];
  private currentWpIndex = 0;
  private targetAlt = 36000;
  private targetSpeed = 450;
  private cruiseAlt = 36000;

  private onUpdateCallback?: (data: TelemetryData) => void;

  init(
    origin: Airport,
    dest: Airport,
    plan?: FlightPlan | null,
    onUpdate?: (data: TelemetryData) => void
  ) {
    this.currentLat = origin.lat;
    this.currentLon = origin.lon;
    this.currentAlt = origin.elevation_ft || 1000;
    this.currentHdg = bearing_deg(origin.lat, origin.lon, dest.lat, dest.lon);
    this.currentSpeed = 0;
    this.currentPitch = 0;
    this.currentRoll = 0;
    this.currentVs = 0;
    this.phaseIndex = 0;
    this.currentWpIndex = 0;
    this.cruiseAlt = plan ? plan.cruise_fl * 100 : 36000;
    this.targetAlt = this.cruiseAlt;
    this.targetSpeed = plan ? plan.tas_kt : 450;

    this.routeWaypoints = [
      { lat: origin.lat, lon: origin.lon, name: origin.icao },
      ...(plan?.waypoints || []),
      { lat: dest.lat, lon: dest.lon, name: dest.icao },
    ];

    if (onUpdate) {
      this.onUpdateCallback = onUpdate;
    }
  }

  setSpeedMultiplier(mult: number) {
    this.simSpeedMultiplier = Math.max(1, Math.min(mult, 20));
  }

  getSpeedMultiplier(): number {
    return this.simSpeedMultiplier;
  }

  isRunning(): boolean {
    return this.active;
  }

  start(onUpdate?: (data: TelemetryData) => void) {
    if (onUpdate) this.onUpdateCallback = onUpdate;
    if (this.active) return;
    this.active = true;

    this.timer = setInterval(() => {
      this.tick();
    }, 500);
  }

  stop() {
    this.active = false;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  jumpToPhase(phase: 'PARKED' | 'TAKEOFF' | 'CRUISE' | 'DESCENT' | 'FINAL') {
    if (this.routeWaypoints.length < 2) return;
    const origin = this.routeWaypoints[0];
    const dest = this.routeWaypoints[this.routeWaypoints.length - 1];

    if (phase === 'PARKED') {
      this.currentLat = origin.lat;
      this.currentLon = origin.lon;
      this.currentAlt = 3782;
      this.currentSpeed = 0;
      this.currentVs = 0;
      this.currentPitch = 0;
      this.currentRoll = 0;
      this.currentWpIndex = 0;
    } else if (phase === 'TAKEOFF') {
      this.currentLat = origin.lat + 0.01;
      this.currentLon = origin.lon + 0.01;
      this.currentAlt = 4500;
      this.currentSpeed = 160;
      this.currentVs = 2200;
      this.currentPitch = 8;
      this.currentRoll = 0;
      this.currentWpIndex = 1;
    } else if (phase === 'CRUISE') {
      // Halfway
      this.currentLat = (origin.lat + dest.lat) / 2;
      this.currentLon = (origin.lon + dest.lon) / 2;
      this.currentAlt = this.cruiseAlt;
      this.currentSpeed = this.targetSpeed;
      this.currentVs = 0;
      this.currentPitch = 1.5;
      this.currentRoll = 0;
      this.currentWpIndex = Math.floor(this.routeWaypoints.length / 2);
    } else if (phase === 'DESCENT') {
      // 80% to dest
      this.currentLat = origin.lat * 0.2 + dest.lat * 0.8;
      this.currentLon = origin.lon * 0.2 + dest.lon * 0.8;
      this.currentAlt = 14000;
      this.currentSpeed = 300;
      this.currentVs = -1800;
      this.currentPitch = -2.5;
      this.currentRoll = 0;
      this.currentWpIndex = this.routeWaypoints.length - 1;
    } else if (phase === 'FINAL') {
      // 5 NM out
      const brg = bearing_deg(origin.lat, origin.lon, dest.lat, dest.lon);
      const rad = ((brg + 180) * Math.PI) / 180;
      const dDeg = 5 / 60;
      this.currentLat = dest.lat + Math.cos(rad) * dDeg;
      this.currentLon = dest.lon + Math.sin(rad) * dDeg;
      this.currentAlt = 2500;
      this.currentSpeed = 145;
      this.currentVs = -750;
      this.currentPitch = 3;
      this.currentRoll = 0;
      this.currentHdg = brg;
      this.currentWpIndex = this.routeWaypoints.length - 1;
    }

    this.broadcast();
  }

  private tick() {
    if (!this.active || this.routeWaypoints.length < 2) return;

    const dtHours = (0.5 * this.simSpeedMultiplier) / 3600; // 500ms scaled
    const dest = this.routeWaypoints[this.routeWaypoints.length - 1];
    const targetWp = this.routeWaypoints[this.currentWpIndex] || dest;

    // Calculate heading toward target waypoint
    const targetHdg = bearing_deg(this.currentLat, this.currentLon, targetWp.lat, targetWp.lon);
    let hdgDiff = ((targetHdg - this.currentHdg + 540) % 360) - 180;
    const turnRate = 3 * this.simSpeedMultiplier; // 3 deg/sec
    if (Math.abs(hdgDiff) > turnRate) {
      this.currentHdg = (this.currentHdg + Math.sign(hdgDiff) * turnRate + 360) % 360;
      this.currentRoll = Math.sign(hdgDiff) * Math.min(25, Math.abs(hdgDiff) * 0.8);
    } else {
      this.currentHdg = targetHdg;
      this.currentRoll = 0;
    }

    // Advance speed
    if (this.currentSpeed < this.targetSpeed) {
      this.currentSpeed = Math.min(this.targetSpeed, this.currentSpeed + 5 * this.simSpeedMultiplier);
    }

    // Altitude profile logic
    const distToDest = distance_nm(this.currentLat, this.currentLon, dest.lat, dest.lon);
    if (distToDest < 10) {
      // Final descent / flare
      this.targetAlt = 1000;
      this.targetSpeed = 135;
      this.currentVs = -600;
      this.currentPitch = 2.5;
      if (distToDest < 0.5) {
        this.currentSpeed = Math.max(0, this.currentSpeed - 15 * this.simSpeedMultiplier);
        this.currentVs = 0;
        this.currentPitch = 0;
      }
    } else if (distToDest < 60) {
      // Descent
      this.targetAlt = 3000;
      this.targetSpeed = 250;
      this.currentVs = -1800;
      this.currentPitch = -2;
    } else {
      // Climb or cruise
      if (this.currentAlt < this.cruiseAlt) {
        this.currentVs = 2000;
        this.currentPitch = 6;
      } else {
        this.currentVs = 0;
        this.currentPitch = 1.5;
      }
    }

    // Apply altitude delta
    const altDelta = (this.currentVs / 60) * 0.5 * this.simSpeedMultiplier;
    this.currentAlt = Math.max(0, this.currentAlt + altDelta);

    // Apply movement along ground track
    const distStepNm = this.currentSpeed * dtHours;
    const radHdg = (this.currentHdg * Math.PI) / 180;
    const dLat = (distStepNm / 60) * Math.cos(radHdg);
    const dLon =
      (distStepNm / (60 * Math.cos((this.currentLat * Math.PI) / 180))) * Math.sin(radHdg);

    this.currentLat += dLat;
    this.currentLon += dLon;

    // Check waypoint arrival
    const distToWp = distance_nm(this.currentLat, this.currentLon, targetWp.lat, targetWp.lon);
    if (distToWp < 3 && this.currentWpIndex < this.routeWaypoints.length - 1) {
      this.currentWpIndex += 1;
    }

    this.broadcast();
  }

  private broadcast() {
    const data: TelemetryData = {
      connected: true,
      transport: 'SIMULATOR',
      lat: Number(this.currentLat.toFixed(5)),
      lon: Number(this.currentLon.toFixed(5)),
      alt: Math.round(this.currentAlt),
      speed: Math.round(this.currentSpeed),
      heading: Math.round(this.currentHdg),
      pitch: Number(this.currentPitch.toFixed(1)),
      roll: Number(this.currentRoll.toFixed(1)),
      vs: Math.round(this.currentVs),
      packets: 1,
      message: `Simulated Telemetry (${this.simSpeedMultiplier}x)`,
      last: Date.now(),
      sim: 'Aerofly FS Global (Internal Sim)',
    };

    if (this.onUpdateCallback) {
      this.onUpdateCallback(data);
    }
  }

  getSnapshot(): TelemetryData {
    return {
      connected: this.active,
      transport: 'SIMULATOR',
      lat: Number(this.currentLat.toFixed(5)),
      lon: Number(this.currentLon.toFixed(5)),
      alt: Math.round(this.currentAlt),
      speed: Math.round(this.currentSpeed),
      heading: Math.round(this.currentHdg),
      pitch: Number(this.currentPitch.toFixed(1)),
      roll: Number(this.currentRoll.toFixed(1)),
      vs: Math.round(this.currentVs),
      packets: 1,
      message: `Simulated Telemetry (${this.simSpeedMultiplier}x)`,
      last: Date.now(),
      sim: 'Aerofly FS Global (Internal Sim)',
    };
  }
}

export const telemetrySimulator = new TelemetrySimulator();
