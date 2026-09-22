# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from genlayer import *

# drand's default public chain (League of Entropy "quicknet" predecessor
# used by the classic /public/{round} endpoint) - verified live against
# https://api.drand.sh/info at design time, not assumed.
DRAND_GENESIS_TIME = 1595431050
DRAND_PERIOD_SECONDS = 30
DRAND_API_BASE = "https://api.drand.sh/public/"

DRAND_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


@allow_storage
@dataclass
class Commitment:
    creator: str
    created_at: u256
    unlock_after: u256
    target_round: u256
    revealed: bool
    randomness_hex: str  # "" until revealed
    modulus: u256  # 0 means "unused" - caller derives their own value
    derived_value: u256  # 0 until revealed (or if modulus is unused)


class BeaconLock(gl.Contract):
    """A generic verifiable-randomness commitment primitive - commit now,
    reveal a consensus-verified public beacon value later.

    This is Fair Draw's commit-then-reveal drand mechanism, extracted from
    its raffle-specific code into a standalone building block any other
    GenLayer contract or off-chain caller can reuse: a random team
    assignment, a shuffle, a lottery, a tie-breaker - anything that needs
    a fair, unpredictable-but-verifiable value without trusting a single
    party to produce it.

    commit(commitment_id, unlock_after) locks in the exact drand round
    that will answer this commitment - computed purely from unlock_after,
    before that round's randomness exists, so nobody (including the
    committer) can know the outcome while choosing unlock_after.
    reveal(commitment_id) - callable once unlock_after has passed - fetches
    that exact round. Validators independently re-fetch it and must agree
    on the raw randomness byte-for-byte before reaching consensus; unlike a
    live-drifting price feed, a finalized drand round is immutable, so the
    randomness itself is consensus-critical here, not a value derived from
    it. Anyone can independently re-fetch the same round from drand's
    public API and confirm the contract's answer themselves.

    An optional modulus, set at commit time, is a convenience for simple
    callers: if provided, reveal() also stores
    derived_value = int(randomness, 16) % modulus, so a caller doesn't have
    to do hex arithmetic themselves. Sophisticated callers can ignore it
    and read randomness_hex directly to derive whatever they need. No
    value ever moves through this contract.
    """

    commitments: TreeMap[str, Commitment]

    def __init__(self):
        pass

    def _now(self) -> int:
        return int(datetime.now(timezone.utc).timestamp())

    @gl.public.write
    def commit(self, commitment_id: str, unlock_after: int, modulus: int = 0) -> None:
        if commitment_id in self.commitments:
            raise gl.vm.UserError(f"Commitment '{commitment_id}' already exists")
        now = self._now()
        if unlock_after <= now:
            raise gl.vm.UserError("unlock_after must be in the future")
        if modulus != 0 and modulus < 2:
            raise gl.vm.UserError("modulus must be 0 (unused) or at least 2")

        target_round = (unlock_after - DRAND_GENESIS_TIME) // DRAND_PERIOD_SECONDS + 1

        self.commitments[commitment_id] = Commitment(
            creator=gl.message.sender_address.as_hex,
            created_at=now,
            unlock_after=unlock_after,
            target_round=target_round,
            revealed=False,
            randomness_hex="",
            modulus=modulus,
            derived_value=0,
        )

    def _fetch_drand_round(self, target_round: int) -> dict:
        def leader_fn() -> dict:
            url = f"{DRAND_API_BASE}{target_round}"
            try:
                resp = gl.nondet.web.request(url, method="GET", headers=DRAND_HEADERS)
                data = json.loads((resp.body or b"").decode("utf-8"))
                randomness = data.get("randomness")
                if not isinstance(randomness, str) or not randomness:
                    return {"found": False, "randomness": ""}
                return {"found": True, "randomness": randomness.lower()}
            except (ValueError, AttributeError, TypeError):
                return {"found": False, "randomness": ""}

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            my_result = leader_fn()
            return (
                my_result["found"] == leaders_res.calldata["found"]
                and my_result["randomness"] == leaders_res.calldata["randomness"]
            )

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @gl.public.write
    def reveal(self, commitment_id: str) -> None:
        if commitment_id not in self.commitments:
            raise gl.vm.UserError(f"Commitment '{commitment_id}' not found")

        c = self.commitments[commitment_id]
        if c.revealed:
            raise gl.vm.UserError("This commitment has already been revealed")
        if self._now() < c.unlock_after:
            raise gl.vm.UserError("unlock_after has not passed yet for this commitment")

        result = self._fetch_drand_round(c.target_round)
        if not result.get("found"):
            raise gl.vm.UserError(
                "Randomness not yet available for this commitment's committed drand pulse - try again shortly"
            )

        randomness_hex = result["randomness"]
        c.revealed = True
        c.randomness_hex = randomness_hex
        if c.modulus > 0:
            c.derived_value = int(randomness_hex, 16) % c.modulus

    @gl.public.view
    def get_commitment(self, commitment_id: str) -> dict:
        if commitment_id not in self.commitments:
            raise gl.vm.UserError(f"Commitment '{commitment_id}' not found")
        c = self.commitments[commitment_id]
        return {
            "creator": c.creator,
            "created_at": c.created_at,
            "unlock_after": c.unlock_after,
            "target_round": c.target_round,
            "revealed": c.revealed,
            "randomness": c.randomness_hex,
            "modulus": c.modulus,
            "derived_value": c.derived_value,
        }
