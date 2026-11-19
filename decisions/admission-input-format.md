# Admit digest evidence in its canonical input format

Use the slot annotation `input_format: sha256` where a text attribute is only meaningful as the canonical lowercase digest of recorded bytes. The archived bundle carries the declaration. Fact loading and admission against the bundle both reject malformed values before those values become rows. The format admits exactly 64 lowercase hexadecimal characters. Equality of these values can correlate two source records. The observations of the source bytes remain separate evidence.

An ordinary LinkML pattern remains a quality check on recorded data. A hard check on every pattern would discard observations needed to diagnose existing findings. The explicit input format uses a fixed validator for SHA-256.
