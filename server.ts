import express from 'express';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';
import { TelemetryParser } from './src/core/telemetryParser.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const server = http.createServer(app);

app.use(express.json());
app.use(express.text({ type: ['text/plain', 'application/x-aerofly'] }));

const telemetryParser = new TelemetryParser();

// Weather API proxies to prevent CORS issues in browser
app.get('/api/metar', async (req, res) => {
  const icao = String(req.query.icao || '').trim().toUpperCase();
  if (!icao) {
    return res.status(400).json({ error: 'Missing icao parameter' });
  }

  try {
    const response = await fetch(
      `https://aviationweather.gov/api/data/metar?ids=${encodeURIComponent(icao)}&format=raw`,
      {
        headers: {
          'User-Agent': 'AeroflyATC/4.1 (simulator companion)',
        },
      }
    );
    const text = await response.text();
    const firstLine = text.split('\n')[0].trim();
    res.json({ icao, raw: firstLine });
  } catch (err: any) {
    res.status(502).json({ error: 'Failed to fetch METAR', details: err.message });
  }
});

app.get('/api/taf', async (req, res) => {
  const icao = String(req.query.icao || '').trim().toUpperCase();
  if (!icao) {
    return res.status(400).json({ error: 'Missing icao parameter' });
  }

  try {
    const response = await fetch(
      `https://aviationweather.gov/api/data/taf?ids=${encodeURIComponent(icao)}&format=raw`,
      {
        headers: {
          'User-Agent': 'AeroflyATC/4.1 (simulator companion)',
        },
      }
    );
    const text = await response.text();
    const firstLine = text.split('\n')[0].trim();
    res.json({ icao, raw: firstLine });
  } catch (err: any) {
    res.status(502).json({ error: 'Failed to fetch TAF', details: err.message });
  }
});

app.get('/api/simbrief', async (req, res) => {
  const username = String(req.query.username || '').trim();
  if (!username) {
    return res.status(400).json({ error: 'Missing username parameter' });
  }

  try {
    const response = await fetch(
      `https://www.simbrief.com/api/xml.fetcher.php?username=${encodeURIComponent(username)}`,
      {
        headers: {
          'User-Agent': 'AeroflyATC/4.1 (simulator companion)',
        },
      }
    );
    const xml = await response.text();
    res.set('Content-Type', 'application/xml');
    res.send(xml);
  } catch (err: any) {
    res.status(502).json({ error: 'Failed to fetch SimBrief plan', details: err.message });
  }
});

// Telemetry bridge endpoint
app.post('/api/telemetry/packet', (req, res) => {
  const body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  telemetryParser.consumeBuffer('', body, req.ip || 'external');
  res.json({ status: 'ok', current: telemetryParser.getSnapshot() });
});

app.get('/api/telemetry/current', (_req, res) => {
  res.json(telemetryParser.getSnapshot());
});

const isProd = process.env.NODE_ENV === 'production';
const PORT = Number(process.env.PORT) || 3000;

async function startServer() {
  if (!isProd) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static(path.resolve(__dirname, 'dist')));
    app.get('*', (_req, res) => {
      res.sendFile(path.resolve(__dirname, 'dist', 'index.html'));
    });
  }

  server.listen(PORT, '0.0.0.0', () => {
    console.log(`Aerofly Air Control server running on http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
