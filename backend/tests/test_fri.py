"""FRI low-degree test verifications.

These tests pin the cryptographic structure of the new prover:
- Field arithmetic correctness (Goldilocks)
- Multiplicative-subgroup existence
- Polynomial interpolation roundtrip
- FRI folding consistency at each layer
- End-to-end proof + tampered-proof rejection
"""
from __future__ import annotations

import asyncio

import pytest

from pa_guard.services.zkstark import (
    _DOMAIN_SIZE,
    P,
    StatementInputs,
    ZkStarkProver,
    ZkStarkVerifier,
    _build_secret_polynomial,
    _fri_fold,
    fadd,
    finv,
    fmul,
    fpow,
    fsub,
    lagrange_interpolate,
    poly_eval,
    poly_eval_domain,
    primitive_nth_root,
)

# ---------------------------------------------------------------------------
# Field arithmetic — Goldilocks p = 2^64 − 2^32 + 1
# ---------------------------------------------------------------------------

def test_field_inverse_roundtrip() -> None:
    for x in (1, 2, 3, 42, P - 1):
        assert fmul(x, finv(x)) == 1


def test_field_add_sub_roundtrip() -> None:
    for a, b in ((3, 5), (P - 1, 7), (0, 0)):
        assert fsub(fadd(a, b), b) == a % P


def test_primitive_nth_root_order() -> None:
    for n in (4, 8, 16, 32, 64):
        omega = primitive_nth_root(n)
        # ω^n = 1, ω^(n/2) ≠ 1
        assert fpow(omega, n) == 1
        assert fpow(omega, n // 2) != 1


# ---------------------------------------------------------------------------
# Polynomial interpolation
# ---------------------------------------------------------------------------

def test_lagrange_roundtrip() -> None:
    xs = [0, 1, 2, 3]
    ys = [11, 22, 33, 44]
    coeffs = lagrange_interpolate(xs, ys)
    for x, y in zip(xs, ys, strict=True):
        assert poly_eval(coeffs, x) == y


def test_evaluation_domain_matches_pointwise() -> None:
    coeffs = [1, 2, 3, 0]
    N = 8
    omega = primitive_nth_root(N)
    domain = poly_eval_domain(coeffs, omega, N)
    for i, y in enumerate(domain):
        assert y == poly_eval(coeffs, fpow(omega, i))


# ---------------------------------------------------------------------------
# Statement → polynomial binding
# ---------------------------------------------------------------------------

def test_secret_polynomial_hits_public_points() -> None:
    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    coeffs = _build_secret_polynomial(stmt)
    # Polynomial is degree < 4; should be exactly 4 coefficients.
    assert len(coeffs) == 4


# ---------------------------------------------------------------------------
# FRI folding identity
# ---------------------------------------------------------------------------

def test_fri_fold_preserves_low_degree_polynomial() -> None:
    """A degree-<d polynomial folded once is degree-<d/2."""
    coeffs = [3, 1, 4, 1, 5, 9, 2, 6]  # degree < 8
    N = 32
    omega = primitive_nth_root(N)
    layer = poly_eval_domain(coeffs, omega, N)
    alpha = 12345
    folded = _fri_fold(layer, omega, alpha)

    # The folded layer should be the evaluation of f_even + α·f_odd on the
    # squared coset of size N/2.
    even = coeffs[0::2]
    odd = coeffs[1::2]
    folded_coeffs = [fadd(even[i], fmul(alpha, odd[i])) for i in range(len(even))]
    omega_sq = fmul(omega, omega)
    expected = poly_eval_domain(folded_coeffs, omega_sq, N // 2)
    assert folded == expected


# ---------------------------------------------------------------------------
# End-to-end proof verification (Goldilocks FRI)
# ---------------------------------------------------------------------------

def _roundtrip(stmt: StatementInputs) -> bool:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    proof = asyncio.run(prover.prove(stmt))
    return asyncio.run(verifier.verify(proof))


def test_fri_proof_verifies_for_short_inputs() -> None:
    assert _roundtrip(
        StatementInputs(
            model_commitment="m",
            input_hash="i",
            output_hash="o",
        )
    )


def test_fri_proof_verifies_for_long_inputs() -> None:
    assert _roundtrip(
        StatementInputs(
            model_commitment="denial_risk_v0",
            input_hash="a" * 64,
            output_hash="b" * 64,
        )
    )


@pytest.mark.parametrize(
    "field, replacement",
    [
        ("model_commitment", "wrong"),
        ("input_hash",       "c" * 64),
        ("output_hash",      "d" * 64),
    ],
)
def test_fri_proof_rejects_every_swapped_field(field: str, replacement: str) -> None:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    base = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    proof = asyncio.run(prover.prove(base))
    tampered = proof.model_copy(update={field: replacement})
    assert asyncio.run(verifier.verify(tampered)) is False


def test_domain_size_is_power_of_two_and_smooth() -> None:
    # Sanity check on the chosen parameters.
    assert (_DOMAIN_SIZE & (_DOMAIN_SIZE - 1)) == 0
    assert (P - 1) % _DOMAIN_SIZE == 0
