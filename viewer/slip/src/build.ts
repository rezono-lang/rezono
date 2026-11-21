import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import { rollup } from '@rollup/wasm-node';
import { compile } from 'svelte/compiler';
import { parse as parseYaml } from 'yaml';
import type { StdPacks } from './types.ts';

const HERE = dirname(fileURLToPath(import.meta.url));
const SLIP_DIR = resolve(HERE, '..');
const REPO_ROOT = resolve(SLIP_DIR, '..', '..');
const VIRTUAL_STD_PACKS = 'virtual:std-packs';
const VIRTUAL_STD_PACKS_RESOLVED = '\0virtual:std-packs';

function readLf(path: string): string {
	return readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');
}

function loadStdPacks(): StdPacks {
	const stdView = resolve(REPO_ROOT, 'packs', 'std-view');
	const stdExplain = resolve(REPO_ROOT, 'packs', 'std-explain');
	const sheets = parseYaml(readLf(resolve(stdView, 'sheets.yaml'))) as {
		verbs?: StdPacks['verbs'];
	};
	const keyDoc = parseYaml(readLf(resolve(stdView, 'key.yaml'))) as {
		signs?: StdPacks['signs'];
		statuses?: StdPacks['statuses'];
	};
	return {
		viewMessages: ['en', 'nl'].map((lang) => ({
			lang,
			resource: readLf(resolve(stdView, 'messages', `${lang}.mf2`)),
		})),
		explainMessages: ['en', 'nl'].map((lang) => ({
			lang,
			resource: readLf(resolve(stdExplain, 'messages', `${lang}.mf2`)),
		})),
		verbs: sheets.verbs ?? [],
		signs: keyDoc.signs ?? [],
		statuses: keyDoc.statuses ?? [],
	};
}

export interface BuiltSlip {
	files: Map<string, Uint8Array>;
	hashes: Record<string, string>;
}

const INDEX_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="./slip.css">
</head>
<body>
<div id="slip-root"></div>
<script type="module" src="./slip.js"></script>
</body>
</html>
`;

export async function buildSlip(): Promise<BuiltSlip> {
	const stdPacks = loadStdPacks();
	const cssByFile = new Map<string, string>();

	const bundle = await rollup({
		input: resolve(HERE, 'main.ts'),
		onwarn(warning, warn) {
			if (warning.code === 'CIRCULAR_DEPENDENCY' && warning.ids?.every((id) => id.includes('svelte'))) {
				return;
			}
			warn(warning);
		},
		plugins: [
			{
				name: 'rezono-slip-virtual-and-transform',
				resolveId(source) {
					if (source === VIRTUAL_STD_PACKS) {
						return VIRTUAL_STD_PACKS_RESOLVED;
					}
					return null;
				},
				load(id) {
					if (id === VIRTUAL_STD_PACKS_RESOLVED) {
						return `export const stdPacks = ${JSON.stringify(stdPacks)};\n`;
					}
					return null;
				},
				transform(code, id) {
					const normalized = code.replace(/\r\n?/g, '\n');
					if (id.endsWith('.svelte')) {
						const name = basename(id);
						const compiled = compile(normalized, {
							filename: name,
							generate: 'client',
							css: 'external',
							dev: false,
						});
						if (compiled.css?.code) {
							cssByFile.set(name, compiled.css.code.replace(/\r\n?/g, '\n'));
						}
						return { code: compiled.js.code, map: null };
					}
					if (id.endsWith('.ts')) {
						return { code: stripTypeScriptTypes(normalized, { mode: 'strip' }), map: null };
					}
					return null;
				},
			},
			nodeResolve({
				browser: true,
				rootDir: SLIP_DIR,
				extensions: ['.mjs', '.js', '.ts', '.svelte', '.json'],
				exportConditions: ['svelte', 'browser', 'import', 'default'],
			}),
		],
	});

	const { output } = await bundle.generate({
		format: 'es',
		inlineDynamicImports: true,
		entryFileNames: 'slip.js',
		generatedCode: { constBindings: true },
	});
	await bundle.close();

	const jsChunk = output.find((item) => item.type === 'chunk');
	if (!jsChunk || jsChunk.type !== 'chunk') {
		throw new Error('Rollup did not produce a JavaScript chunk for the slip');
	}

	const cssText = [...cssByFile.entries()]
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
		.map(([, css]) => css)
		.join('\n')
		.trimEnd();

	const encoder = new TextEncoder();
	const files = new Map<string, Uint8Array>([
		['index.html', encoder.encode(INDEX_HTML)],
		['slip.css', encoder.encode(cssText ? `${cssText}\n` : '')],
		['slip.js', encoder.encode(jsChunk.code.replace(/\r\n?/g, '\n'))],
	]);

	const hashes: Record<string, string> = {};
	for (const [name, bytes] of files) {
		hashes[name] = createHash('sha256').update(bytes).digest('hex');
	}
	return { files, hashes };
}
