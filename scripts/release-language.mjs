import { mkdirSync, readFileSync, readdirSync, writeFileSync, cpSync } from 'node:fs';
import { join } from 'node:path';
import { stripTypeScriptTypes } from 'node:module';

const [dest, compilerReader] = process.argv.slice(2);
mkdirSync(join(dest, 'src'), { recursive: true });
const pkg = JSON.parse(readFileSync('rezono/package.json', 'utf8'));
const { name, version, description, engines, type, dependencies } = pkg;
writeFileSync(join(dest, 'package.json'), JSON.stringify({
  name, version, description, engines, type, dependencies, exports: './src/index.js',
  repository: { type: 'git', url: 'git+https://github.com/rezono-lang/rezono.git' },
  license: 'Apache-2.0',
}, null, 2));
for (const file of [...readdirSync('rezono/src').filter(f => f.endsWith('.ts')), 'canon.ts']) {
  const source = file === 'canon.ts' ? 'viewer/src/lib/canon.ts' : join('rezono/src', file);
  const js = stripTypeScriptTypes(readFileSync(source, 'utf8'))
    .replaceAll("'../../viewer/src/lib/canon.ts'", "'./canon.js'")
    .replace(/(from\s+['"]\.\/[^'"]+)\.ts(['"])/g, '$1.js$2');
  writeFileSync(join(dest, 'src', file.replace(/\.ts$/, '.js')), js);
}
for (const file of ['LICENSE', 'NOTICE', 'LICENSES', 'rezono/messages', 'rezono/README.md']) {
  cpSync(file, join(dest, file.split('/').at(-1)), { recursive: true });
}

if (compilerReader) {
  const lock = JSON.parse(readFileSync('rezono/package-lock.json', 'utf8'));
  const ohm = 'rezono/node_modules/ohm-js';
  const locked = lock.packages['node_modules/ohm-js'];
  const installed = JSON.parse(readFileSync(join(ohm, 'package.json'), 'utf8'));
  if (locked.version !== dependencies['ohm-js'] || installed.version !== locked.version || installed.license !== 'MIT')
    throw Error('The locked Ohm runtime must be installed with npm ci in rezono/');
  for (const file of ['package.json', 'src', 'messages']) {
    cpSync(join(dest, file), join(compilerReader, file), { recursive: true });
  }
  const runtime = join(compilerReader, 'node_modules/ohm-js');
  mkdirSync(join(runtime, 'dist'), { recursive: true });
  cpSync(join(ohm, 'dist/ohm.cjs'), join(runtime, 'dist/ohm.cjs'));
  cpSync(join(ohm, 'LICENSE'), join(runtime, 'LICENSE'));
  writeFileSync(join(runtime, 'package.json'), JSON.stringify({
    name: 'ohm-js', version: locked.version, main: './dist/ohm.cjs', license: 'MIT',
  }));
}
