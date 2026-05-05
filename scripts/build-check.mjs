import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const requiredFiles = [
  'api/index.py',
  'power_site_mvp/__init__.py',
  'power_site_mvp/app/main.py',
  'power_site_mvp/templates/index.html',
  'power_site_mvp/templates/login.html',
  'power_site_mvp/static/app.js',
  'power_site_mvp/static/style.css',
  'requirements.txt',
  'vercel.json'
];

for (const file of requiredFiles) {
  if (!existsSync(file)) {
    throw new Error(`Missing required deploy file: ${file}`);
  }
}

execFileSync(process.execPath, ['--check', 'power_site_mvp/static/app.js'], { stdio: 'inherit' });
console.log('PowerSite Scout OS root build check passed.');
