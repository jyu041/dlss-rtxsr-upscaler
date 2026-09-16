from src.core.dlssg_official_runtime import EXPECTED_PROVIDER_SHA256, EXPECTED_PROVIDER_SIZE, policy_satisfied


def test_official_provider_policy_is_exact():
    assert policy_satisfied(f"nvngx_dlssg.dll:{EXPECTED_PROVIDER_SIZE}:{EXPECTED_PROVIDER_SHA256}")
    assert not policy_satisfied(f"nvngx_dlssg.dll:{EXPECTED_PROVIDER_SIZE + 1}:{EXPECTED_PROVIDER_SHA256}")
    assert not policy_satisfied("missing")
