# Schema identity and metadata

Declare module identity once. A schema header may also carry 'prefix name = iri', 'import iri', and 'default range Type' (prefixes map, imports list, defaultRange string). Schema, kind, slot and enum member blocks support description, exact mapping and annotation lines, encoded as description text, exactMappings ordered strings, and annotations keyed by name. Annotation values use typed JSON literals with exact decimal text for numeric fields. Validate against the named annotation's schema. The written name supplies its label. Translations and explicit exceptions can override it. Flattening these fields into comments would lose data during publication.

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
