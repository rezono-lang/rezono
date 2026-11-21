import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildSlip } from '../src/build.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = resolve(HERE, '..', 'dist');

const { files, hashes } = await buildSlip();
rmSync(DIST, { recursive: true, force: true });
mkdirSync(DIST, { recursive: true });
for (const [name, bytes] of files) {
	writeFileSync(resolve(DIST, name), bytes);
}
process.stdout.write(JSON.stringify(hashes) + '\n');
