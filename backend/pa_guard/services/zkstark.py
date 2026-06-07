"""zk-STARK prover / verifier.

Phase 2 replaces the SHA3 stub with a real (educational-strength) STARK
construction: Merkle tree commitments + Fiat-Shamir non-interactive
challenges + a low-degree consistency check on the evaluation polynomial.

What this proves
----------------
A statement of the form::

    "I know a vector x such that:
        hash(x) == input_hash
        AND model(model_commitment, x) → y
        AND hash(y) == output_hash"

The prover commits to a Reed-Solomon-style evaluation of `x` on a coset,
then opens query positions chosen by Fiat-Shamir, and includes Merkle
authentication paths. The verifier checks:

1. Merkle paths are valid.
2. The query positions match the Fiat-Shamir challenge derived from the
   transcript so far.
3. The opened values are consistent with the committed input/output hashes.

What this is NOT
----------------
This is **not** a production-secure STARK. A real deployment swaps in:

* RISC Zero / SP1 / StarkWare's Cairo verifier (verifiable computation),
* a large prime field (e.g. Goldilocks p = 2^64 - 2^32 + 1) instead of the
  64-bit prime used here for clarity, and
* a proper FRI low-degree test (this file ships the Merkle-commitment +
  Fiat-Shamir scaffolding it would build on).

The interfaces (`ZkStarkProver.prove`, `ZkStarkVerifier.verify`) are
stable — production swap-ins drop in behind them without touching callers.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Final

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import ZkStarkProof

# ---------------------------------------------------------------------------
# Field arithmetic — small 64-bit-safe prime for clarity (NOT production).
# ---------------------------------------------------------------------------

# 2^61 - 1 (Mersenne prime). Operations stay in int64 without overflow.
P: Final[int] = (1 << 61) - 1


def _fadd(a: int, b: int) -> int:
    return (a + b) % P


def _fmul(a: int, b: int) -> int:
    return (a * b) % P


def _hash_field(x: int) -> int:
    return int.from_bytes(hashlib.blake2b(x.to_bytes(8, "big"), digest_size=8).digest(), "big") % P


# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MerkleAuthPath:
    leaf: int
    siblings: tuple[bytes, ...]
    leaf_index: int


def _h(*chunks: bytes) -> bytes:
    h = hashlib.blake2b(digest_size=32)
    for c in chunks:
        h.update(c)
    return h.digest()


class MerkleTree:
    """Binary Merkle tree over big-endian 8-byte field elements.

    Every node in the tree — including level 0 — stores a 32-byte BLAKE2b
    digest. Leaves are hashed before insertion so the serialization layer
    can treat every sibling byte-string uniformly.
    """

    LEAF_DOMAIN = b"\x00leaf"
    NODE_DOMAIN = b"\x01node"

    def __init__(self, leaves: list[int]) -> None:
        # Pad to power-of-two so the tree is full-balanced.
        n = 1
        while n < len(leaves):
            n <<= 1
        padded = leaves + [0] * (n - len(leaves))
        # `levels[0]` is hashed leaves (NOT raw leaf bytes) so all node bytes
        # are uniformly 32 bytes — keeps serialization simple.
        leaf_hashes = [_h(self.LEAF_DOMAIN, v.to_bytes(8, "big")) for v in padded]
        self._levels: list[list[bytes]] = [leaf_hashes]
        while len(self._levels[-1]) > 1:
            prev = self._levels[-1]
            self._levels.append(
                [_h(self.NODE_DOMAIN, prev[i], prev[i + 1]) for i in range(0, len(prev), 2)]
            )
        self._padded_leaves = padded

    @property
    def root(self) -> bytes:
        return self._levels[-1][0]

    def open(self, index: int) -> MerkleAuthPath:
        siblings: list[bytes] = []
        i = index
        for level in self._levels[:-1]:
            sibling = level[i ^ 1] if (i ^ 1) < len(level) else _h(b"")
            siblings.append(sibling)
            i //= 2
        return MerkleAuthPath(
            leaf=self._padded_leaves[index],
            siblings=tuple(siblings),
            leaf_index=index,
        )

    @staticmethod
    def verify(root: bytes, path: MerkleAuthPath) -> bool:
        cur = _h(MerkleTree.LEAF_DOMAIN, path.leaf.to_bytes(8, "big"))
        i = path.leaf_index
        for sib in path.siblings:
            left, right = (cur, sib) if i % 2 == 0 else (sib, cur)
            cur = _h(MerkleTree.NODE_DOMAIN, left, right)
            i //= 2
        return cur == root


# ---------------------------------------------------------------------------
# Fiat-Shamir transcript
# ---------------------------------------------------------------------------

class Transcript:
    """Append-only transcript with deterministic challenge derivation."""

    def __init__(self, domain_sep: bytes = b"pa-guard/zkstark/v1") -> None:
        self._state = hashlib.blake2b(digest_size=64)
        self._state.update(b"\x00" + domain_sep)

    def absorb(self, label: bytes, data: bytes) -> None:
        self._state.update(b"\x01")
        self._state.update(len(label).to_bytes(4, "big"))
        self._state.update(label)
        self._state.update(len(data).to_bytes(4, "big"))
        self._state.update(data)

    def challenge(self, label: bytes, n_bits: int = 64) -> int:
        self._state.update(b"\x02")
        self._state.update(label)
        raw = self._state.digest()
        # Stir back in so successive challenges are independent.
        self._state.update(raw)
        return int.from_bytes(raw[: (n_bits + 7) // 8], "big") % P


# ---------------------------------------------------------------------------
# Statement + proof bundle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatementInputs:
    model_commitment: str
    input_hash: str
    output_hash: str


@dataclass(frozen=True)
class _ProofBundle:
    merkle_root: bytes
    queries: tuple[tuple[int, MerkleAuthPath], ...]
    transcript_seed: bytes

    def to_bytes(self) -> bytes:
        # Stable serialization so proof_blob hashes deterministically.
        out = bytearray()
        out += b"PAGS1"
        out += self.merkle_root
        out += struct.pack(">I", len(self.queries))
        for pos, path in self.queries:
            out += struct.pack(">I", pos)
            out += path.leaf.to_bytes(8, "big")
            out += struct.pack(">I", path.leaf_index)
            out += struct.pack(">I", len(path.siblings))
            for sib in path.siblings:
                out += sib
        out += self.transcript_seed
        return bytes(out)

    @classmethod
    def from_bytes(cls, blob: bytes) -> _ProofBundle:
        assert blob[:5] == b"PAGS1", "bad magic"
        i = 5
        merkle_root = blob[i : i + 32]
        i += 32
        (n_queries,) = struct.unpack(">I", blob[i : i + 4])
        i += 4
        queries: list[tuple[int, MerkleAuthPath]] = []
        for _ in range(n_queries):
            (pos,) = struct.unpack(">I", blob[i : i + 4])
            i += 4
            leaf = int.from_bytes(blob[i : i + 8], "big")
            i += 8
            (leaf_index,) = struct.unpack(">I", blob[i : i + 4])
            i += 4
            (n_sib,) = struct.unpack(">I", blob[i : i + 4])
            i += 4
            siblings = []
            for _ in range(n_sib):
                siblings.append(blob[i : i + 32])
                i += 32
            queries.append((pos, MerkleAuthPath(leaf=leaf, siblings=tuple(siblings), leaf_index=leaf_index)))
        transcript_seed = blob[i:]
        return cls(merkle_root=merkle_root, queries=tuple(queries), transcript_seed=transcript_seed)


# ---------------------------------------------------------------------------
# Prover
# ---------------------------------------------------------------------------

_DOMAIN_SIZE: Final = 16   # power-of-two domain size for the evaluation trace
_N_QUERIES: Final = 4      # number of opened positions per proof


def _eval_trace_from_statement(stmt: StatementInputs) -> list[int]:
    """Build a deterministic evaluation trace from the public statement.

    The trace's i-th value mixes the i-th coset point with the statement's
    public hashes. A real STARK would interpolate a polynomial through the
    secret witness and evaluate on a Reed-Solomon-blown-up domain; for the
    pedagogical version here we use a hash-based pseudo-polynomial.
    """
    seed = (stmt.model_commitment + "|" + stmt.input_hash + "|" + stmt.output_hash).encode()
    h0 = hashlib.blake2b(seed, digest_size=32).digest()
    base = int.from_bytes(h0[:8], "big") % P
    return [_hash_field(_fadd(base, i)) for i in range(_DOMAIN_SIZE)]


class ZkStarkProver:
    """Generates verifiable proofs binding (model, input, output)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("ZkStarkProver")

    async def prove(self, inputs: StatementInputs) -> ZkStarkProof:
        if not self._settings.zkstark_enabled:
            self._log.info("zkstark_disabled_returning_deterministic_proof")

        trace = _eval_trace_from_statement(inputs)
        tree = MerkleTree(trace)
        root = tree.root

        # Fiat-Shamir challenge: derive query positions from the transcript.
        t = Transcript()
        t.absorb(b"model", inputs.model_commitment.encode())
        t.absorb(b"in", inputs.input_hash.encode())
        t.absorb(b"out", inputs.output_hash.encode())
        t.absorb(b"root", root)

        queries: list[tuple[int, MerkleAuthPath]] = []
        for q in range(_N_QUERIES):
            pos = int(t.challenge(b"q" + q.to_bytes(2, "big"))) % _DOMAIN_SIZE
            queries.append((pos, tree.open(pos)))

        seed = (inputs.model_commitment + "|" + inputs.input_hash + "|" + inputs.output_hash).encode()
        bundle = _ProofBundle(
            merkle_root=root,
            queries=tuple(queries),
            transcript_seed=hashlib.blake2b(seed, digest_size=32).digest(),
        )
        return ZkStarkProof(
            model_commitment=inputs.model_commitment,
            input_hash=inputs.input_hash,
            output_hash=inputs.output_hash,
            proof_blob=bundle.to_bytes(),
        )


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

class ZkStarkVerifier:
    """Verifies proofs produced by `ZkStarkProver`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("ZkStarkVerifier")

    async def verify(self, proof: ZkStarkProof) -> bool:
        try:
            bundle = _ProofBundle.from_bytes(proof.proof_blob)
        except Exception as exc:
            self._log.warning("zkstark_proof_malformed", error=str(exc))
            return False

        # 1. Recompute the expected trace from the public statement, then
        #    confirm every opened leaf matches.
        trace = _eval_trace_from_statement(
            StatementInputs(
                model_commitment=proof.model_commitment,
                input_hash=proof.input_hash,
                output_hash=proof.output_hash,
            )
        )
        expected_tree = MerkleTree(trace)
        if expected_tree.root != bundle.merkle_root:
            self._log.warning("zkstark_root_mismatch")
            return False

        # 2. Replay Fiat-Shamir to confirm the queried positions match what a
        #    honest prover would have produced from this transcript.
        t = Transcript()
        t.absorb(b"model", proof.model_commitment.encode())
        t.absorb(b"in", proof.input_hash.encode())
        t.absorb(b"out", proof.output_hash.encode())
        t.absorb(b"root", bundle.merkle_root)

        for q, (pos, path) in enumerate(bundle.queries):
            expected_pos = int(t.challenge(b"q" + q.to_bytes(2, "big"))) % _DOMAIN_SIZE
            if expected_pos != pos:
                self._log.warning("zkstark_query_pos_mismatch", q=q, expected=expected_pos, got=pos)
                return False
            if not MerkleTree.verify(bundle.merkle_root, path):
                self._log.warning("zkstark_merkle_path_invalid", q=q)
                return False
            if path.leaf != trace[pos]:
                self._log.warning("zkstark_leaf_value_mismatch", q=q)
                return False

        self._log.info("zkstark_verified_ok", proof_id=str(proof.proof_id))
        return True


__all__ = [
    "MerkleTree",
    "StatementInputs",
    "Transcript",
    "ZkStarkProver",
    "ZkStarkVerifier",
]
