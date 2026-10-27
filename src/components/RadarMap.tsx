import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { Airport, FlightPlan, TelemetryData } from '../types/aviation';
import { great_circle_points } from '../core/plannerCore';
import { Crosshair, Layers, Compass, Eye, MapPin, ZoomIn, ZoomOut } from 'lucide-react';

interface RadarMapProps {
  telemetry: TelemetryData;
  origin: Airport;
  dest: Airport;
  flightPlan: FlightPlan | null;
}

export const RadarMap: React.FC<RadarMapProps> = ({
  telemetry,
  origin,
  dest,
  flightPlan,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const aircraftMarkerRef = useRef<L.Marker | null>(null);
  const routeLayerRef = useRef<L.LayerGroup | null>(null);
  const rangeRingsLayerRef = useRef<L.LayerGroup | null>(null);
  const tileLayerRef = useRef<L.TileLayer | null>(null);

  const [autoFollow, setAutoFollow] = useState(true);
  const [mapStyle, setMapStyle] = useState<'DARK' | 'TACTICAL' | 'TERRAIN'>('DARK');
  const [showRings, setShowRings] = useState(true);

  // Initialize Leaflet map
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (mapRef.current) return;

    const initialLat = telemetry.lat ?? origin.lat;
    const initialLon = telemetry.lon ?? origin.lon;

    const map = L.map(mapContainerRef.current, {
      center: [initialLat, initialLon],
      zoom: 8,
      zoomControl: false,
      attributionControl: false,
    });

    // ESRI Dark Gray Canvas - free, high quality, no API key watermark
    const tileLayer = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      {
        maxZoom: 16,
        attribution: 'Tiles &copy; Esri',
      }
    ).addTo(map);

    tileLayerRef.current = tileLayer;
    routeLayerRef.current = L.layerGroup().addTo(map);
    rangeRingsLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    // Aircraft Icon with SVG
    const aircraftIcon = L.divIcon({
      className: 'aircraft-marker-container',
      html: `
        <div id="aircraft-icon-wrapper" style="transform: rotate(${telemetry.heading}deg); transition: transform 0.25s linear; width: 36px; height: 36px; display: flex; items-center; justify-content: center;">
          <svg viewBox="0 0 24 24" width="34" height="34" fill="#00e5ff" style="filter: drop-shadow(0 0 6px rgba(0,229,255,0.8));">
            <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
          </svg>
        </div>
      `,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    });

    aircraftMarkerRef.current = L.marker([initialLat, initialLon], {
      icon: aircraftIcon,
      zIndexOffset: 1000,
    }).addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update map tile style
  useEffect(() => {
    if (!mapRef.current || !tileLayerRef.current) return;
    mapRef.current.removeLayer(tileLayerRef.current);

    let url =
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
    if (mapStyle === 'TERRAIN') {
      url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    } else if (mapStyle === 'TACTICAL') {
      url =
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
    }

    tileLayerRef.current = L.tileLayer(url, { maxZoom: 18 }).addTo(mapRef.current);
  }, [mapStyle]);

  // Update route lines, airports, TOC/TOD
  useEffect(() => {
    if (!mapRef.current || !routeLayerRef.current) return;
    const layer = routeLayerRef.current;
    layer.clearLayers();

    // Origin airport marker
    const originIcon = L.divIcon({
      className: 'origin-marker',
      html: `
        <div class="px-2 py-0.5 rounded bg-emerald-950/90 border border-emerald-500 text-[10px] font-mono font-bold text-emerald-300 shadow-md">
          ${origin.icao}
        </div>
      `,
      iconAnchor: [20, 10],
    });
    L.marker([origin.lat, origin.lon], { icon: originIcon }).addTo(layer);

    // Destination airport marker
    const destIcon = L.divIcon({
      className: 'dest-marker',
      html: `
        <div class="px-2 py-0.5 rounded bg-amber-950/90 border border-amber-500 text-[10px] font-mono font-bold text-amber-300 shadow-md">
          ${dest.icao}
        </div>
      `,
      iconAnchor: [20, 10],
    });
    L.marker([dest.lat, dest.lon], { icon: destIcon }).addTo(layer);

    // Great circle route line
    const curvePoints = great_circle_points(origin.lat, origin.lon, dest.lat, dest.lon, 20);
    const latLngs = curvePoints.map(([lat, lon]) => [lat, lon] as [number, number]);

    L.polyline(latLngs, {
      color: '#00d2ff',
      weight: 3,
      dashArray: '6, 6',
      opacity: 0.85,
    }).addTo(layer);

    // Add TOC and TOD markers if flight plan exists
    if (flightPlan && curvePoints.length > 2) {
      const totalPts = curvePoints.length;
      const tocRatio = Math.min(0.4, flightPlan.toc_nm / flightPlan.distance_nm);
      const todRatio = Math.max(0.6, flightPlan.tod_nm / flightPlan.distance_nm);

      const tocIdx = Math.floor(tocRatio * totalPts);
      const todIdx = Math.floor(todRatio * totalPts);

      if (curvePoints[tocIdx]) {
        const tocIcon = L.divIcon({
          className: 'toc-marker',
          html: `<div class="px-1.5 py-0.5 rounded bg-cyan-900 border border-cyan-400 text-[9px] font-mono text-cyan-200">TOC</div>`,
        });
        L.marker([curvePoints[tocIdx][0], curvePoints[tocIdx][1]], { icon: tocIcon }).addTo(layer);
      }

      if (curvePoints[todIdx]) {
        const todIcon = L.divIcon({
          className: 'tod-marker',
          html: `<div class="px-1.5 py-0.5 rounded bg-indigo-900 border border-indigo-400 text-[9px] font-mono text-indigo-200">TOD</div>`,
        });
        L.marker([curvePoints[todIdx][0], curvePoints[todIdx][1]], { icon: todIcon }).addTo(layer);
      }
    }
  }, [origin, dest, flightPlan]);

  // Update Aircraft position and range rings on telemetry tick
  useEffect(() => {
    if (!mapRef.current) return;
    const lat = telemetry.lat ?? origin.lat;
    const lon = telemetry.lon ?? origin.lon;

    if (aircraftMarkerRef.current) {
      aircraftMarkerRef.current.setLatLng([lat, lon]);

      // Update rotation
      const wrapper = document.getElementById('aircraft-icon-wrapper');
      if (wrapper) {
        wrapper.style.transform = `rotate(${telemetry.heading}deg)`;
      }
    }

    if (autoFollow && mapRef.current) {
      mapRef.current.panTo([lat, lon], { animate: true, duration: 0.5 });
    }

    // Range rings
    if (rangeRingsLayerRef.current) {
      rangeRingsLayerRef.current.clearLayers();
      if (showRings) {
        const nmRadii = [5, 10, 20, 40];
        nmRadii.forEach((nm) => {
          const meters = nm * 1852;
          L.circle([lat, lon], {
            radius: meters,
            color: '#00e5ff',
            weight: 1,
            dashArray: '3, 6',
            fill: false,
            opacity: 0.25,
          }).addTo(rangeRingsLayerRef.current!);
        });
      }
    }
  }, [telemetry.lat, telemetry.lon, telemetry.heading, autoFollow, showRings, origin.lat, origin.lon]);

  const centerOnAircraft = () => {
    if (!mapRef.current) return;
    const lat = telemetry.lat ?? origin.lat;
    const lon = telemetry.lon ?? origin.lon;
    mapRef.current.setView([lat, lon], 10, { animate: true });
    setAutoFollow(true);
  };

  const centerOnRoute = () => {
    if (!mapRef.current) return;
    const bounds = L.latLngBounds([
      [origin.lat, origin.lon],
      [dest.lat, dest.lon],
      [telemetry.lat ?? origin.lat, telemetry.lon ?? origin.lon],
    ]);
    mapRef.current.fitBounds(bounds, { padding: [50, 50] });
    setAutoFollow(false);
  };

  return (
    <div className="relative w-full h-[calc(100vh-140px)] min-h-[500px] bg-slate-950 rounded-xl overflow-hidden border border-cyan-900/40 shadow-2xl">
      {/* Leaflet Container */}
      <div ref={mapContainerRef} className="w-full h-full z-0" />

      {/* Top Map Controls Overlay */}
      <div className="absolute top-4 left-4 z-10 flex flex-wrap items-center gap-2">
        <button
          onClick={centerOnAircraft}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-medium border shadow-md backdrop-blur-md transition-all ${
            autoFollow
              ? 'bg-cyan-600 text-white border-cyan-400'
              : 'bg-slate-900/80 text-slate-300 border-slate-700 hover:bg-slate-800'
          }`}
        >
          <Crosshair className="w-4 h-4" />
          <span>FOLLOW AC</span>
        </button>

        <button
          onClick={centerOnRoute}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-medium bg-slate-900/80 text-slate-300 border border-slate-700 hover:bg-slate-800 shadow-md backdrop-blur-md transition-all"
        >
          <MapPin className="w-4 h-4 text-emerald-400" />
          <span>FIT ROUTE</span>
        </button>

        <button
          onClick={() => setShowRings(!showRings)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono font-medium border shadow-md backdrop-blur-md transition-all ${
            showRings
              ? 'bg-cyan-950/80 text-cyan-300 border-cyan-600'
              : 'bg-slate-900/80 text-slate-400 border-slate-700'
          }`}
        >
          <Compass className="w-4 h-4" />
          <span>RADAR RINGS</span>
        </button>

        <div className="flex rounded-lg overflow-hidden border border-slate-700 bg-slate-900/80 text-xs font-mono">
          <button
            onClick={() => setMapStyle('DARK')}
            className={`px-2.5 py-1.5 ${
              mapStyle === 'DARK' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            DARK
          </button>
          <button
            onClick={() => setMapStyle('TACTICAL')}
            className={`px-2.5 py-1.5 border-l border-slate-700 ${
              mapStyle === 'TACTICAL' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            TACTICAL
          </button>
          <button
            onClick={() => setMapStyle('TERRAIN')}
            className={`px-2.5 py-1.5 border-l border-slate-700 ${
              mapStyle === 'TERRAIN' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-white'
            }`}
          >
            TERRAIN
          </button>
        </div>
      </div>

      {/* Zoom Buttons Overlay */}
      <div className="absolute top-4 right-4 z-10 flex flex-col gap-1.5">
        <button
          onClick={() => mapRef.current?.zoomIn()}
          className="p-2 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700 shadow-md"
          title="Zoom In"
        >
          <ZoomIn className="w-4 h-4" />
        </button>
        <button
          onClick={() => mapRef.current?.zoomOut()}
          className="p-2 rounded-lg bg-slate-900/90 hover:bg-slate-800 text-cyan-300 border border-slate-700 shadow-md"
          title="Zoom Out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>
      </div>

      {/* Floating Tactical Radar Compass Overlay (Bottom-Right) */}
      <div className="absolute bottom-4 right-4 z-10 bg-slate-950/85 border border-cyan-900/60 rounded-xl p-3 shadow-xl backdrop-blur-md hidden sm:block">
        <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 mb-2 border-b border-slate-800 pb-1">
          <span className="font-bold text-cyan-400">TACTICAL RADAR</span>
          <span>RANGE 40 NM</span>
        </div>
        <div className="relative w-28 h-28 mx-auto flex items-center justify-center border border-cyan-500/30 rounded-full">
          {/* Radar Sweep line */}
          <div className="absolute inset-0 rounded-full border border-cyan-500/20" />
          <div className="absolute w-20 h-20 rounded-full border border-cyan-500/20" />
          <div className="absolute w-10 h-10 rounded-full border border-cyan-500/20" />
          {/* Compass cross */}
          <div className="absolute w-full h-[1px] bg-cyan-500/20" />
          <div className="absolute h-full w-[1px] bg-cyan-500/20" />
          <span className="absolute top-0.5 text-[9px] font-mono font-bold text-cyan-400">N</span>
          <span className="absolute bottom-0.5 text-[9px] font-mono font-bold text-slate-500">S</span>
          <span className="absolute right-1 text-[9px] font-mono font-bold text-slate-500">E</span>
          <span className="absolute left-1 text-[9px] font-mono font-bold text-slate-500">W</span>

          {/* Aircraft pointer in center */}
          <div
            className="w-4 h-4 flex items-center justify-center transition-transform duration-300"
            style={{ transform: `rotate(${telemetry.heading}deg)` }}
          >
            <div className="w-0 h-0 border-l-[4px] border-l-transparent border-r-[4px] border-r-transparent border-b-[8px] border-b-cyan-400" />
          </div>
        </div>
        <div className="mt-2 text-center font-mono text-xs text-cyan-300 font-bold">
          TRACK: {telemetry.heading.toString().padStart(3, '0')}°
        </div>
      </div>
    </div>
  );
};
