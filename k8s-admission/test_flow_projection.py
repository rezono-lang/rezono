"""The model has already derived the flows. Publication preserves their tuple identity."""

import pytest


def test_same_namespace_flow_rows_are_unique_and_numerically_ordered():
    from flow_projection import project_flows

    rows = [("blue", "reader", "web", 443), ("green", "probe", "web", 8443),
            ("blue", "reader", "web", 80), ("blue", "reader", "web", 443)]
    assert project_flows("blue", rows) == [
        {"source": "reader", "destination": "web", "port": 80},
        {"source": "reader", "destination": "web", "port": 443}]
    assert project_flows("green", rows) == [
        {"source": "probe", "destination": "web", "port": 8443}]
    assert project_flows("amber", rows) == []
