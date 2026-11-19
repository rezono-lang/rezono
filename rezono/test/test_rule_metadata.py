from reader_case import assert_reader_case


def test_rule_metadata():
    """Rule annotations stay verbatim lines of a relational block (decisions/language-rules.md)."""
    assert_reader_case("rule_metadata")
