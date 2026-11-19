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

## A keyword as a schema name

`example` is a keyword of v0, like the other words in its keyword list: it starts the declaration `example "…"` of a worked example. So `schema example` is refused with R000 at `example`, as any keyword is where a name is expected. This is intended, and the keyword list stays fixed: making `example` a contextual word would make the list depend on position for one word that a later declaration needs.

A schema whose name is a keyword, such as a converted LinkML schema named `example`, writes it in backticks: `` schema `example` ``. The JSON holds the name without backticks, `"schema": "example"`, and the printer writes the backticks back. This is how a backticked rule name already denotes the exact identifier between the backticks. Renaming the schema during conversion was considered; it would change the name that publication and the schema IRI carry.

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
