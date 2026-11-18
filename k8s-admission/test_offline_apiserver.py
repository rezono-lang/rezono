import pytest

from offline_oracle_cases import check_offline_oracle


@pytest.mark.xfail(strict=True, reason="Depends on the desired release and manual policies. Implement the upstream Kubernetes apiserver policy and binding evaluator in k8s-admission/oracles/apiserver, with locked dependencies; read decisions/k8s-admission-oracles.md.")
def test_offline_apiserver_accepts_only_the_published_cases(tmp_path):
    check_offline_oracle("apiserver", tmp_path)
