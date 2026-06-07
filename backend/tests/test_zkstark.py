"""zk-STARK prover / verifier tests — Merkle + Fiat-Shamir + opening."""
from __future__ import annotations

import pytest

from pa_guard.services.zkstark import (
    MerkleTree,
    StatementInputs,
    Transcript,
    ZkStarkProver,
    ZkStarkVerifier,
)

# ---------------------------------------------------------------------------
# Merkle tree
# ---------------------------------------------------------------------------

def test_merkle_tree_roundtrip() -> None:
    tree = MerkleTree([1, 2, 3, 4, 5, 6, 7, 8])
    for i in range(8):
        path = tree.open(i)
        assert MerkleTree.verify(tree.root, path) is True


def test_merkle_tree_rejects_tampered_leaf() -> None:
    tree = MerkleTree([1, 2, 3, 4])
    path = tree.open(2)
    tampered = type(path)(
        leaf=path.leaf + 1, siblings=path.siblings, leaf_index=path.leaf_index
    )
    assert MerkleTree.verify(tree.root, tampered) is False


def test_merkle_tree_rejects_tampered_index() -> None:
    tree = MerkleTree([10, 20, 30, 40])
    path = tree.open(1)
    tampered = type(path)(
        leaf=path.leaf, siblings=path.siblings, leaf_index=path.leaf_index ^ 1
    )
    assert MerkleTree.verify(tree.root, tampered) is False


# ---------------------------------------------------------------------------
# Transcript (Fiat-Shamir)
# ---------------------------------------------------------------------------

def test_transcript_is_deterministic() -> None:
    t1 = Transcript()
    t1.absorb(b"a", b"hello")
    c1 = t1.challenge(b"x")

    t2 = Transcript()
    t2.absorb(b"a", b"hello")
    c2 = t2.challenge(b"x")

    assert c1 == c2


def test_transcript_changes_with_input() -> None:
    t1 = Transcript()
    t1.absorb(b"a", b"hello")
    c1 = t1.challenge(b"x")

    t2 = Transcript()
    t2.absorb(b"a", b"world")
    c2 = t2.challenge(b"x")

    assert c1 != c2


# ---------------------------------------------------------------------------
# Prover / verifier roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proof_roundtrip_verifies() -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()

    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    proof = await prover.prove(stmt)
    assert await verifier.verify(proof) is True


@pytest.mark.asyncio
async def test_proof_rejects_swapped_input_hash() -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    proof = await prover.prove(stmt)
    tampered = proof.model_copy(update={"input_hash": "c" * 64})
    assert await verifier.verify(tampered) is False


@pytest.mark.asyncio
async def test_proof_rejects_swapped_output_hash() -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    proof = await prover.prove(stmt)
    tampered = proof.model_copy(update={"output_hash": "c" * 64})
    assert await verifier.verify(tampered) is False


@pytest.mark.asyncio
async def test_proof_rejects_swapped_model_commitment() -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    proof = await prover.prove(stmt)
    tampered = proof.model_copy(update={"model_commitment": "denial_risk_v9"})
    assert await verifier.verify(tampered) is False


@pytest.mark.asyncio
async def test_proof_rejects_malformed_blob() -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    stmt = StatementInputs(
        model_commitment="m", input_hash="i", output_hash="o",
    )
    proof = await prover.prove(stmt)
    tampered = proof.model_copy(update={"proof_blob": b"BAD\x00MAGIC"})
    assert await verifier.verify(tampered) is False
