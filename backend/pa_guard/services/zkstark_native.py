"""Optional native acceleration shim.

When the `zkstark_native` Rust extension is installed (built from
`native/zkstark-accel/`), this module re-exports the hot-loop primitives
(`poly_eval_domain`, `fri_fold`, `merkle_root`) AND the full prove / verify
pair — all matching the pure-Python `zkstark.py` semantics bit-for-bit.

Without the wheel installed, every flag is `False` and every callable is
`None`; the pure-Python path is untouched. There is no performance cost to
keeping the shim imported.

Install for local development:

    cd native/zkstark-accel
    pip install maturin && maturin develop --release

CI builds the multi-platform wheels as part of the release pipeline.
"""
from __future__ import annotations

from typing import Any

# Hot-loop primitives.
HAS_NATIVE: bool = False
fri_fold: Any = None
poly_eval_domain: Any = None
merkle_root: Any = None

# Full prove / verify.
HAS_NATIVE_PROVE: bool = False
HAS_NATIVE_VERIFY: bool = False
prove: Any = None
verify: Any = None


try:
    import zkstark_native as _native  # type: ignore[import-not-found]
except ImportError:
    _native = None

if _native is not None:
    fri_fold = _native.fri_fold
    poly_eval_domain = _native.poly_eval_domain
    merkle_root = _native.merkle_root
    HAS_NATIVE = True
    if hasattr(_native, "prove"):
        prove = _native.prove
        HAS_NATIVE_PROVE = True
    if hasattr(_native, "verify"):
        verify = _native.verify
        HAS_NATIVE_VERIFY = True


__all__ = [
    "HAS_NATIVE",
    "HAS_NATIVE_PROVE",
    "HAS_NATIVE_VERIFY",
    "fri_fold",
    "merkle_root",
    "poly_eval_domain",
    "prove",
    "verify",
]
