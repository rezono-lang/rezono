# Schema identity and metadata

Declare module identity once. A schema header may also carry 'prefix name = iri', 'import iri', and 'default range Type' (prefixes map, imports list, defaultRange string). Schema, kind, slot and enum member blocks support description, exact mapping and annotation lines, encoded as description text, exactMappings ordered strings, and annotations keyed by name. Annotation values use typed JSON literals with exact decimal text for numeric fields. Validate against the named annotation's schema. The written name supplies its label. Translations and explicit exceptions can override it. Flattening these fields into comments would lose data during publication.

Indent the header fields under `schema name`. Write prefix and import IRIs as quoted strings, descriptions as `description "text"`, and annotations as `annotation name = value`. Indent `iri "rdfs:label"` under a slot to set that slot's `slotUri`. It carries LinkML `slot_uri` separately from `exactMappings`, which describe equivalences. Preserve the written IRI or CURIE without expanding it.

```rezono
schema collection
  iri "urn:example:collection"
  language en
```

The corresponding JSON fragment is

```json
{
  "schema": "collection",
  "iri": "urn:example:collection",
  "language": "en"
}
```
