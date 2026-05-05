import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const script = 'scripts/bootstrap_stable.py';
const candidates = process.platform === 'win32' ? ['python', 'py'] : ['python3', 'python'];

if (!existsSync(script)) {
  console.error(`Missing bootstrap script: ${script}`);
  process.exit(1);
}

let lastError = null;
for (const command of candidates) {
  const result = spawnSync(command, [script], { stdio: 'inherit', shell: false });
  if (result.error) {
    lastError = result.error;
    if (result.error.code === 'ENOENT') {
      continue;
    }
    console.error(result.error.message);
    process.exit(1);
  }
  process.exit(result.status ?? 0);
}

console.error(`No usable Python command found. Tried: ${candidates.join(', ')}`);
if (lastError) {
  console.error(lastError.message);
}
process.exit(1);
