"""Direct-mode tests for the BeaconLock contract."""

import json
from datetime import datetime, timezone

CONTRACT = "contracts/beacon_lock.py"

DRAND_GENESIS_TIME = 1595431050
DRAND_PERIOD_SECONDS = 30

T0 = "2026-01-01T00:00:00Z"
T0_TS = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
UNLOCK_AFTER = T0_TS + 600  # 10 minutes out
TARGET_ROUND = (UNLOCK_AFTER - DRAND_GENESIS_TIME) // DRAND_PERIOD_SECONDS + 1

T_BEFORE_UNLOCK = "2026-01-01T00:05:00Z"  # 5 min in - still locked
T_AFTER_UNLOCK = "2026-01-01T00:10:01Z"  # just past unlock_after

RANDOMNESS_A = "7f2a91cd4e0b8f61a3d5c9027fbe114c6a8d0f5e2b9741ac83d6f0e2b4179a2e"


def _mock_drand(vm, target_round: int, randomness_hex: str | None, found: bool = True):
    vm.clear_mocks()
    if found:
        body = json.dumps({"round": target_round, "randomness": randomness_hex})
        status = 200
    else:
        body = json.dumps({"error": "not found"})
        status = 404
    vm.mock_web(
        r"api\.drand\.sh/public/" + str(target_round) + r"$",
        {"method": "GET", "status": status, "body": body},
    )


def test_commit_creates_commitment(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    contract.commit("draft-order", UNLOCK_AFTER)

    c = contract.get_commitment("draft-order")
    assert c["created_at"] == T0_TS
    assert c["unlock_after"] == UNLOCK_AFTER
    assert c["target_round"] == TARGET_ROUND
    assert c["revealed"] is False
    assert c["randomness"] == ""
    assert c["modulus"] == 0
    assert c["derived_value"] == 0


def test_commit_duplicate_id_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    with direct_vm.expect_revert("already exists"):
        contract.commit("draft-order", UNLOCK_AFTER)


def test_commit_past_unlock_after_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("must be in the future"):
        contract.commit("draft-order", T0_TS - 1)


def test_commit_negative_modulus_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("must be 0"):
        contract.commit("draft-order", UNLOCK_AFTER, -1)


def test_commit_modulus_one_fails(direct_vm, direct_deploy, direct_alice):
    """modulus=1 would silently always produce derived_value=0 - reject it
    rather than let a caller accidentally rely on a value that never
    varies, mistaking it for randomness."""
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("must be 0"):
        contract.commit("draft-order", UNLOCK_AFTER, 1)


def test_reveal_before_unlock_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    direct_vm.warp(T_BEFORE_UNLOCK)
    with direct_vm.expect_revert("has not passed yet"):
        contract.reveal("draft-order")


def test_reveal_unknown_commitment_fails(direct_vm, direct_deploy):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("not found"):
        contract.reveal("nonexistent")


def test_get_commitment_unknown_fails(direct_vm, direct_deploy):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("not found"):
        contract.get_commitment("nonexistent")


def test_reveal_without_modulus_stores_raw_randomness_only(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    direct_vm.warp(T_AFTER_UNLOCK)
    _mock_drand(direct_vm, TARGET_ROUND, RANDOMNESS_A)
    contract.reveal("draft-order")

    c = contract.get_commitment("draft-order")
    assert c["revealed"] is True
    assert c["randomness"] == RANDOMNESS_A
    assert c["target_round"] == TARGET_ROUND
    assert c["modulus"] == 0
    assert c["derived_value"] == 0


def test_reveal_with_modulus_computes_derived_value(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("team-shuffle", UNLOCK_AFTER, 4)

    direct_vm.warp(T_AFTER_UNLOCK)
    _mock_drand(direct_vm, TARGET_ROUND, RANDOMNESS_A)
    contract.reveal("team-shuffle")

    c = contract.get_commitment("team-shuffle")
    assert c["revealed"] is True
    assert c["randomness"] == RANDOMNESS_A
    assert c["modulus"] == 4
    assert c["derived_value"] == int(RANDOMNESS_A, 16) % 4


def test_reveal_already_revealed_fails(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    direct_vm.warp(T_AFTER_UNLOCK)
    _mock_drand(direct_vm, TARGET_ROUND, RANDOMNESS_A)
    contract.reveal("draft-order")

    with direct_vm.expect_revert("already been revealed"):
        contract.reveal("draft-order")


def test_reveal_reverts_cleanly_when_randomness_unavailable(
    direct_vm, direct_deploy, direct_alice
):
    """The committed drand round hasn't been published yet (or the fetch
    failed) - must revert cleanly, not crash, and leave the commitment
    re-revealable once the pulse is actually available."""
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    direct_vm.warp(T_AFTER_UNLOCK)
    _mock_drand(direct_vm, TARGET_ROUND, None, found=False)

    with direct_vm.expect_revert("Randomness not yet available"):
        contract.reveal("draft-order")

    assert contract.get_commitment("draft-order")["revealed"] is False

    _mock_drand(direct_vm, TARGET_ROUND, RANDOMNESS_A)
    contract.reveal("draft-order")
    assert contract.get_commitment("draft-order")["revealed"] is True


def test_reveal_exactly_at_unlock_after_succeeds(direct_vm, direct_deploy, direct_alice):
    """commit() requires unlock_after strictly in the future (> now at
    commit time); reveal() must allow the symmetric boundary - now ==
    unlock_after - not require it to have strictly passed."""
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    from datetime import datetime, timezone

    boundary = datetime.fromtimestamp(UNLOCK_AFTER, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    direct_vm.warp(boundary)
    _mock_drand(direct_vm, TARGET_ROUND, RANDOMNESS_A)
    contract.reveal("draft-order")

    assert contract.get_commitment("draft-order")["revealed"] is True


def test_independent_commitments_compute_distinct_target_rounds(
    direct_vm, direct_deploy, direct_alice
):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice

    later_unlock = UNLOCK_AFTER + 300
    later_target_round = (later_unlock - DRAND_GENESIS_TIME) // DRAND_PERIOD_SECONDS + 1

    contract.commit("a", UNLOCK_AFTER)
    contract.commit("b", later_unlock)

    assert contract.get_commitment("a")["target_round"] == TARGET_ROUND
    assert contract.get_commitment("b")["target_round"] == later_target_round
    assert TARGET_ROUND != later_target_round


def test_commitment_records_creator(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    direct_vm.warp(T0)
    direct_vm.sender = direct_alice
    contract.commit("draft-order", UNLOCK_AFTER)

    from tests.direct.conftest import to_hex

    assert contract.get_commitment("draft-order")["creator"] == to_hex(direct_alice)
