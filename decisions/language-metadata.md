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

## Close and broad mappings

A kind, slot or enum member may also carry LinkML `close_mappings` and `broad_mappings`. Write them like an exact mapping: `close mapping "iri"` and `broad mapping "iri"`, one per line, in the metadata block of that declaration. They are encoded as `closeMappings` and `broadMappings`, ordered string lists beside `exactMappings`, and lower to the LinkML lists of the same name in written order. The three kinds stay distinct because they state different equivalences; folding a close or broad mapping into an exact one would overstate it.

```rezono
kind Ground world closed
  close mapping "prov:Influence"
  rests_on: Decision
    close mapping "prov:wasInfluencedBy"
    broad mapping "dcterms:relation"
```

The slot's JSON fragment is

```json
{
  "slot": "rests_on",
  "type": "Decision",
  "closeMappings": ["prov:wasInfluencedBy"],
  "broadMappings": ["dcterms:relation"]
}
```
