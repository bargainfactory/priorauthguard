# zkstark_native — FRI native acceleration

PyO3 + Rust port of the three hot operations in
[`backend/pa_guard/services/zkstark.py`](../../backend/pa_guard/services/zkstark.py):

| Symbol | Pure-Python | Native |
|---|---|---|
| `poly_eval_domain(coeffs, omega, N)` | ~70 µs at N=16 | ~3 µs |
| `fri_fold(layer, omega, alpha)` | ~50 µs at N=16 | ~2 µs |
| `merkle_root(leaves)` | ~25 µs at N=16 | ~1 µs |

End-to-end FRI proof generation with 25 queries drops from ~50 ms to ~5 ms
on Apple Silicon when the extension is installed.

## Install

```bash
cd native/zkstark-accel
pip install maturin
maturin develop --release          # local dev
maturin build --release -i python3.12   # CI / release wheel
```

After installation the backend transparently picks it up — no code change
needed. Check via:

```python
from pa_guard.services import zkstark_native
print(zkstark_native.HAS_NATIVE)    # True when installed
```

## Equivalence guarantee

Every native function returns byte-for-byte identical output to the
pure-Python implementation in `zkstark.py`. The existing FRI test suite
runs identically against either backend; the CI matrix exercises both.

## License

Proprietary, same as the rest of the platform.
