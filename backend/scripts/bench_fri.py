"""Microbenchmark — pure-Python FRI vs native acceleration.

Usage:
    python -m pa_guard.scripts.bench_fri          # default 200 iterations
    python -m pa_guard.scripts.bench_fri --iter 500

Prints per-call latency for `poly_eval_domain`, `fri_fold`, and an
end-to-end `prove + verify` cycle, plus the speedup factor when
`zkstark_native` is installed.
"""
from __future__ import annotations

import argparse
import asyncio
import time

from pa_guard.services import zkstark_native
from pa_guard.services.zkstark import (
    StatementInputs,
    ZkStarkProver,
    ZkStarkVerifier,
    _fri_fold_py,
    _poly_eval_domain_py,
    primitive_nth_root,
)


def _bench(label: str, fn, *args, iters: int) -> float:
    # Warm-up.
    for _ in range(5):
        fn(*args)
    t0 = time.perf_counter()
    for _ in range(iters):
        fn(*args)
    elapsed_ms = (time.perf_counter() - t0) * 1000 / iters
    print(f"  {label:<35s} {elapsed_ms:8.3f} ms/call")
    return elapsed_ms


async def _bench_prove_verify(iters: int) -> tuple[float, float]:
    prover = ZkStarkProver()
    verifier = ZkStarkVerifier()
    stmt = StatementInputs(
        model_commitment="denial_risk_v0",
        input_hash="a" * 64,
        output_hash="b" * 64,
    )
    # Warm-up.
    proof = await prover.prove(stmt)
    await verifier.verify(proof)

    t0 = time.perf_counter()
    for _ in range(iters):
        proof = await prover.prove(stmt)
    prove_ms = (time.perf_counter() - t0) * 1000 / iters

    t0 = time.perf_counter()
    for _ in range(iters):
        await verifier.verify(proof)
    verify_ms = (time.perf_counter() - t0) * 1000 / iters
    return prove_ms, verify_ms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iter", type=int, default=200)
    args = parser.parse_args()

    print(f"Native acceleration: {'AVAILABLE' if zkstark_native.HAS_NATIVE else 'NOT INSTALLED'}")
    if not zkstark_native.HAS_NATIVE:
        print("  (install via `pip install maturin && cd native/zkstark-accel && maturin develop --release`)")
    print()

    coeffs = [3, 1, 4, 1]
    N = 16
    omega = primitive_nth_root(N)
    layer = _poly_eval_domain_py(coeffs, omega, N)
    alpha = 12345

    print("Hot-loop microbenchmarks:")
    py_eval = _bench("poly_eval_domain (Python)", _poly_eval_domain_py, coeffs, omega, N, iters=args.iter)
    if zkstark_native.HAS_NATIVE:
        nat_eval = _bench(
            "poly_eval_domain (native)",
            zkstark_native.poly_eval_domain,
            coeffs, omega, N,
            iters=args.iter,
        )
        print(f"    speedup: {py_eval / max(nat_eval, 1e-9):>6.1f}x")

    py_fold = _bench("fri_fold (Python)", _fri_fold_py, layer, omega, alpha, iters=args.iter)
    if zkstark_native.HAS_NATIVE:
        nat_fold = _bench(
            "fri_fold (native)",
            zkstark_native.fri_fold,
            layer, omega, alpha,
            iters=args.iter,
        )
        print(f"    speedup: {py_fold / max(nat_fold, 1e-9):>6.1f}x")

    print()
    print("End-to-end FRI prove + verify (25 queries):")
    prove_ms, verify_ms = asyncio.run(_bench_prove_verify(iters=max(20, args.iter // 10)))
    print(f"  prove   {prove_ms:8.2f} ms")
    print(f"  verify  {verify_ms:8.2f} ms")


if __name__ == "__main__":
    main()
