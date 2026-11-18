import pytest

from offline_oracle_cases import check_offline_oracle


def test_offline_apiserver_accepts_only_the_published_cases(tmp_path):
    check_offline_oracle("apiserver", tmp_path)
