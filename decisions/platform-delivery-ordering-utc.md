# Delivery numbers use the admitted UTC instant

Order a tenant's submitted services by their admitted UTC timestamps and use service names to break ties. The delivery rules read the actual timestamp on each request. Older facts can still carry the optional numeric keys, which the delivery rules ignore.

The `utc_instant` input format checks calendar and clock fields at admission. It accepts `Z` and `+00:00`, writes the exact fractional value without trailing zeros, and emits the `+00:00` suffix. The fixed UTC fields sort in chronological order. Within an equal second, the suffix sorts before the fractional separator or the next fractional digit. Equal instants therefore admit the same value, and longer fractional precision survives admission.

The rule-level `@text_order` opt-in makes `<` a lexical comparison of UTF-8 text in its annotated rule. It keeps timestamp and service-name comparisons explicit in the rule IR and in independent witness checking. The file preview uses the same admission path as direct pack facts.
