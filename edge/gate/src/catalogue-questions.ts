const fields = ['kind_id', 'entry_type', 'name', 'effective_world', 'coverage',
	'row_presence', 'value_type', 'slot_card'] as const;

export const catalogueFields = [...fields, 'kind_name'] as const;
const show = fields.map((field) => 'entry.' + field).join(', ');

export const catalogueKindsQuestion =
	'ask entry: CatalogueEntry where entry.entry_type = "kind" show ' + show;

export function catalogueSchemaQuestion(identifier: string): string {
	const name = JSON.stringify(identifier);
	return 'ask entry: CatalogueEntry where entry.kind_id = ' + name
		+ ' or entry.kind_name = ' + name + ' show ' + show;
}
