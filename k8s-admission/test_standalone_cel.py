import pytest

from offline_oracle_cases import check_offline_oracle


def test_standalone_cel_accepts_only_the_published_cases(tmp_path):
    check_offline_oracle("cel", tmp_path)
