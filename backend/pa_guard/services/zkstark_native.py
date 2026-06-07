"""Optional native acceleration for the FRI hot loops.

When the `zkstark_native` Rust extension is installed (built from
`native/zkstark-accel/`), this module dispatches the hot path
(`fri_fold`, `poly_eval_domain`, `merkle_root`) to it. Otherwise every call
falls through to the pure-Python implementation in `zkstark.py`.

The interface is a single capability flag plus three drop-in functions
matching the pure-Python signatures. The caller doesn't need to know which
backend served a given call — `zkstark.py` consults `HAS_NATIVE` once at
import time and binds the right symbol.

To install the native wheel for local development:

```bash
cd native/zkstark-accel
maturin develop --release
```

CI builds the wheel as part of the release pipeline (Phase 6 CI template).
"""
from __future__ import annotations

from typing import Any

# Public capability flag — the only thing the pure-Python module reads.
HAS_NATIVE: bool = False

# When HAS_NATIVE is True, these bind to the Rust implementations and match
# the pure-Python signatures exactly. We start them as `None` so the import
# never blows up if the extension isn't compiled.
fri_fold: Any = None
poly_eval_domain: Any = None
merkle_root: Any = None


try:
    import zkstark_native as _native  # type: ignore[import-not-found]
except ImportError:
    _native = None

if _native is not None:
    # The Rust crate exposes these symbols at the module level. If the
    # crate's surface drifts, we want a hard ImportError at startup rather
    # than a silent fall-through to Python — so getattr without a default.
    fri_fold = _native.fri_fold
    poly_eval_domain = _native.poly_eval_domain
    merkle_root = _native.merkle_root
    HAS_NATIVE = True


__all__ = ["HAS_NATIVE", "fri_fold", "merkle_root", "poly_eval_domain"]
