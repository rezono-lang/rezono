import pytest

from offline_oracle_cases import check_offline_oracle


@pytest.mark.xfail(strict=True, reason="Depends on the desired release and manual policies. Implement the typed cel-go expression evaluator in k8s-admission/oracles/cel, with locked dependencies; read decisions/k8s-admission-oracles.md.")
def test_standalone_cel_accepts_only_the_published_cases(tmp_path):
    check_offline_oracle("cel", tmp_path)
