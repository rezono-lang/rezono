import assert from 'node:assert/strict';
import { test } from 'node:test';
import { loadThemeFile, renderExcerptSvg, tokenizeLine } from '../src/render-excerpt-svg.ts';

test('renderExcerptSvg: double-quoted string literals are highlighted with the string token color', () => {
	const theme = loadThemeFile();
	const stringColor = theme.themes.light.tokens.string;
	const svg = renderExcerptSvg('label = "hello \\"world\\""', theme.themes.light);
	assert.match(
		svg,
		new RegExp(`<tspan fill="${stringColor}">&quot;hello \\\\&quot;world\\\\&quot;&quot;</tspan>`),
	);
});

test('tokenizeLine: nested capture groups never duplicate text or rewind cursor', () => {
	const line = 'abc';
	const spans = tokenizeLine(line, [
		{
			regex: /((a)(b)c)/duy,
			scope: 'meta.test.rezono',
			captures: {
				'1': { name: 'entity.name.type.rezono' },
				'2': { name: 'keyword.control.rezono' },
				'3': { name: 'constant.numeric.rezono' },
			},
		},
	]);
	assert.equal(spans.map((s) => s.text).join(''), line);
});
