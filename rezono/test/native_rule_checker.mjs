import { readFileSync } from 'node:fs';
import * as language from '../src/index.ts';

const cases = JSON.parse(readFileSync(0, 'utf8'));
const diagnostics = typeof language.checkModuleRules === 'function'
    ? cases.map(({ form, schema, source }) => language.checkModuleRules(form, schema, source).diagnostics)
    : null;
process.stdout.write(JSON.stringify(diagnostics));
