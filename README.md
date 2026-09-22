# Beacon Lock
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/license/mit/)
[![Discord](https://img.shields.io/badge/Discord-Join%20us-5865F2?logo=discord&logoColor=white)](https://discord.gg/8Jm4v89VAu)
[![Telegram](https://img.shields.io/badge/Telegram--T.svg?style=social&logo=telegram)](https://t.me/genlayer)
[![Twitter](https://img.shields.io/twitter/url/https/twitter.com/yeagerai.svg?style=social&label=Follow%20%40GenLayer)](https://x.com/GenLayer)

## About
Beacon Lock is a generic **verifiable-randomness commitment** primitive - a
GenLayer Intelligent Contract with no LLM anywhere in it, and no external
randomness trust assumption beyond a public beacon anyone can check
themselves.

It is [Fair Draw](https://github.com/2TheMoom/fair-draw)'s commit-then-reveal
drand mechanism, extracted from its raffle-specific code into a standalone
building block. Fair Draw bakes "commit a round, reveal a winner" into one
raffle contract; Beacon Lock keeps just the commitment core so *any* other
GenLayer contract, or an off-chain caller, can reuse it directly for a
raffle, a shuffle, a random team assignment, a tie-breaker - anything that
needs a fair, unpredictable-but-verifiable value without reimplementing
beacon-round math or consensus logic, and without trusting a single party to
produce the outcome.

`commit(commitment_id, unlock_after, modulus=0)` locks in the exact
[drand](https://drand.love) public randomness beacon round that will answer
this commitment, computed purely from `unlock_after`:

```
target_round = (unlock_after - DRAND_GENESIS_TIME) // DRAND_PERIOD_SECONDS + 1
```

That round is fixed the instant `commit()` is called - before its
randomness value exists - so nobody, including the committer, can know the
outcome while choosing `unlock_after`. `reveal(commitment_id)` - callable
once `unlock_after` has passed - fetches that exact round. Validators
independently re-fetch it and must agree on the raw randomness byte-for-byte
before reaching consensus via the equivalence principle; unlike a
live-drifting price feed, a finalized drand round is immutable, so the
randomness itself is consensus-critical here, not a value derived from it.

An optional `modulus`, set at commit time, is a convenience for simple
callers: if provided, `reveal()` also stores
`derived_value = int(randomness, 16) % modulus`, so a caller doesn't have to
do hex arithmetic themselves. Sophisticated callers can ignore it and read
`randomness_hex` directly to derive whatever they need - the full raw value
is always public via `get_commitment`, so anyone can independently re-fetch
the same round from `api.drand.sh/public/{round}` and confirm the contract's
answer without trusting its word for it. No value ever moves through this
contract.

## Deployment
Deployed on **GenLayer Bradbury Testnet** (chain ID 4221):
- **Contract:** [`0x7c83Fc3E0c5959b8B6ac6aac92a5CE5620e10B6f`](https://explorer-bradbury.genlayer.com/address/0x7c83Fc3E0c5959b8B6ac6aac92a5CE5620e10B6f)
- Verified via 13 passing direct-mode tests (`python -m pytest tests/direct/`),
  covering commitment creation, past/duplicate/negative-input validation,
  reveal-before-unlock and unknown-commitment reverts, a clean
  revert-then-succeed once randomness becomes available, both the
  bare-randomness and `modulus`-derived reveal paths, double-reveal
  rejection, and independent commitments computing distinct target rounds
  from different `unlock_after` values.
- Verified live end-to-end against the real drand public API (not just
  direct-mode tests): committed with `modulus=6` (a fair die roll), waited
  for the real target round's scheduled publish time to pass, and called
  `reveal()` - validators reached full 5/5 consensus and the contract
  recorded drand round `6488916`. Independently re-fetching that exact
  round from `api.drand.sh/public/6488916` returns the byte-identical
  randomness the contract stored, and recomputing
  `int(randomness, 16) % 6` by hand gives `0`, matching the contract's own
  `derived_value: 0` exactly - the result is reproducible from the public
  beacon alone, without trusting this contract's word for it.

## What's included
- `contracts/beacon_lock.py` — the BeaconLock Intelligent Contract
- `tests/direct/test_beacon_lock.py` — direct-mode tests (in-memory, mocked drand API, time-warped)
- **Contract linting** — static analysis to catch common contract issues before deployment
- **CI pipeline** — GitHub Actions workflow for linting and direct tests
- Configuration file template and a deployment script

This is a contract-only primitive, deliberately without a frontend - the
point is to be called by other contracts and integrators, not to be a
product on its own.

## Requirements
- Python >= 3.12
- [GenLayer CLI](https://github.com/genlayerlabs/genlayer-cli) globally installed: `npm install -g genlayer`
- GenLayer Studio (for integration tests and deployment): Install from [Docs](https://docs.genlayer.com/developers/intelligent-contracts/tooling-setup#using-the-genlayer-studio) or use the hosted [GenLayer Studio](https://studio.genlayer.com/)

## Project Structure

```
contracts/              # Python intelligent contracts
  beacon_lock.py           # Beacon Lock
tests/
  direct/                # Fast in-memory tests (no Studio required)
    test_beacon_lock.py
deploy/                  # TypeScript deployment scripts
gltest.config.yaml       # Test runner network configuration
pyproject.toml           # Python/pytest configuration
.github/workflows/       # CI pipeline
```

## Quick Start

### 1. Set up Python environment

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Lint the contract

```shell
genvm-lint check contracts/beacon_lock.py
```

### 3. Run direct mode tests

```shell
python -m pytest tests/direct/ -v
```

Use `python -m pytest`, not bare `pytest` - depending on your installed
pytest version, running the bare command can fail to put the project
root on `sys.path`, breaking test discovery with
`ModuleNotFoundError: No module named 'tests'`.

### 4. Deploy the contract

1. Choose your network: `genlayer network`
2. Deploy: `genlayer deploy` (runs the script in `/deploy/deployScript.ts`)

## How Beacon Lock Works

1. **`commit(commitment_id, unlock_after, modulus=0)`** — locks in the
   exact drand round that will answer this commitment, computed purely
   from `unlock_after`. Reverts if the id already exists, `unlock_after`
   isn't in the future, or `modulus` is negative.
2. **`reveal(commitment_id)`** — callable once `unlock_after` has passed.
   Fetches the committed drand round; if it isn't published yet, reverts
   cleanly and can be retried. On success, stores the raw randomness and,
   if `modulus > 0`, the derived value.
3. **`get_commitment(commitment_id)`** — reads back a commitment's full
   state: creator, timing, target round, and (once revealed) the raw
   randomness and derived value.

### Example: a two-line coin flip

```python
# In some other contract, or from a script:
beacon_lock.commit("flip-1", now() + 60, modulus=2)
# ... wait past unlock_after ...
beacon_lock.reveal("flip-1")
heads = beacon_lock.get_commitment("flip-1")["derived_value"] == 0
```

## Testing Strategy

| Test Type | Command | Speed | Requires Studio |
|-----------|---------|-------|-----------------|
| **Lint** | `genvm-lint check contracts/beacon_lock.py` | ~250ms | No |
| **Direct** | `python -m pytest tests/direct/ -v` | ~ms/test | No |

## Community
- **[Discord](https://discord.gg/8Jm4v89VAu)**: Discussions, support, and announcements
- **[Telegram](https://t.me/genlayer)**: Informal chats and quick updates

## Documentation
For detailed information, see our [documentation](https://docs.genlayer.com/).

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
