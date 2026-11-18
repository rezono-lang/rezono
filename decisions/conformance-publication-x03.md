# Independent LinkML export oracle

Source `docs/publication/cases/X03.yaml#X03`.

## Deferral

This case requires a LinkML export of the fixture pack and two independent comparisons. LinkML's JSON-LD context must yield the same triples, and its SHACL output must agree on the R01 document. The existing [RDF tests](../publication/tests/test_rdf.py) cover publication RDF behavior without establishing both comparisons for that export.

Revisit when an exported fixture can be fed to both LinkML generators and the outputs can be compared with the same Rezono publication, including an input that validation rejects.
