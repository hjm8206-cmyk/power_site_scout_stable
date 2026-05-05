import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const zipUrl = process.env.POWERSITE_STABLE_ZIP_URL || 'https://fairy-clarity-knitting-municipality.trycloudflare.com/static/powersite-vercel-sync.zip';
const zipPath = '/tmp/powersite-vercel-sync.zip';

function runPython(script) {
  const candidates = ['python3', 'python'];
  let lastError = null;
  for (const command of candidates) {
    try {
      execFileSync(command, ['-c', script], { stdio: 'inherit' });
      return;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error('Python runtime not available');
}

async function downloadWithRetry(url, attempts = 5) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      console.log(`Downloading stable PowerSite source zip (${attempt}/${attempts})...`);
      const response = await fetch(url, { redirect: 'follow' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
      }
      const buffer = Buffer.from(await response.arrayBuffer());
      if (buffer.length < 1000) {
        throw new Error(`Downloaded zip is unexpectedly small: ${buffer.length} bytes`);
      }
      writeFileSync(zipPath, buffer);
      console.log(`Downloaded ${buffer.length} bytes.`);
      return;
    } catch (error) {
      lastError = error;
      console.warn(`Download attempt failed: ${error.message}`);
      await new Promise((resolve) => setTimeout(resolve, attempt * 2500));
    }
  }
  throw lastError;
}

await downloadWithRetry(zipUrl);

if (existsSync('power_site_mvp')) {
  rmSync('power_site_mvp', { recursive: true, force: true });
}

const extractScript = String.raw`
import pathlib
import zipfile

root = pathlib.Path('.').resolve()
zip_path = pathlib.Path('/tmp/powersite-vercel-sync.zip')
forbidden = []
with zipfile.ZipFile(zip_path) as zf:
    for name in zf.namelist():
        normalized = name.replace('\\', '/')
        parts = set(normalized.split('/'))
        if parts & {'.env', 'private_data', 'reports', 'backups', '.packages', '.local_run_packages', '__pycache__', '.vercel', 'node_modules'}:
            forbidden.append(name)
        if normalized.endswith(('.log', '.pid')):
            forbidden.append(name)
    if forbidden:
        raise SystemExit('Forbidden files in source zip: ' + ', '.join(forbidden[:20]))
    zf.extractall(root)

required = [
    root / 'power_site_mvp' / 'api' / 'index.py',
    root / 'power_site_mvp' / 'app' / 'main.py',
    root / 'power_site_mvp' / 'app' / 'parcel.py',
    root / 'power_site_mvp' / 'app' / 'vworld.py',
    root / 'power_site_mvp' / 'static' / 'app.js',
    root / 'power_site_mvp' / 'templates' / 'index.html',
]
missing = [str(path) for path in required if not path.exists()]
if missing:
    raise SystemExit('Stable source zip missing files: ' + ', '.join(missing))
print('Stable PowerSite source extracted for Vercel build.')
`;

runPython(extractScript);

mkdirSync('public', { recursive: true });
writeFileSync('public/index.html', '<!doctype html><meta charset="utf-8"><title>PowerSite Scout OS</title><p>PowerSite Scout OS</p>\n');
console.log('Bootstrap complete:', zipUrl);
