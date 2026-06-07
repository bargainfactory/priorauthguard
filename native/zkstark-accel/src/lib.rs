//! Native acceleration for the pure-Python FRI prover.
//!
//! The pure-Python module exposes a stable surface:
//!
//!   - `poly_eval_domain(coeffs, omega, N) -> [u64; N]`
//!   - `fri_fold(layer, omega, alpha) -> [u64; N/2]`
//!   - `merkle_root(leaves) -> bytes`
//!
//! All field arithmetic is in the Goldilocks field
//! (p = 2^64 - 2^32 + 1). The implementations below mirror the Python ones
//! bit-for-bit so existing tests pass identically against either backend.
//!
//! Build with `maturin develop --release` (dev) or `maturin build --release`
//! (CI).

use blake2::digest::consts::U32;
use blake2::{Blake2b, Digest};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

const P: u128 = (1u128 << 64) - (1u128 << 32) + 1;
const LEAF_DOMAIN: &[u8] = b"\x00leaf";
const NODE_DOMAIN: &[u8] = b"\x01node";

type Blake2b256 = Blake2b<U32>;

#[inline(always)]
fn fadd(a: u64, b: u64) -> u64 {
    ((a as u128 + b as u128) % P) as u64
}

#[inline(always)]
fn fsub(a: u64, b: u64) -> u64 {
    ((a as i128 - b as i128).rem_euclid(P as i128)) as u64
}

#[inline(always)]
fn fmul(a: u64, b: u64) -> u64 {
    ((a as u128 * b as u128) % P) as u64
}

fn fpow(mut a: u64, mut n: u64) -> u64 {
    let mut acc: u64 = 1;
    a = (a as u128 % P) as u64;
    while n > 0 {
        if n & 1 == 1 {
            acc = fmul(acc, a);
        }
        a = fmul(a, a);
        n >>= 1;
    }
    acc
}

#[inline(always)]
fn finv(a: u64) -> u64 {
    fpow(a, (P - 2) as u64)
}

fn poly_eval_native(coeffs: &[u64], x: u64) -> u64 {
    let mut acc: u64 = 0;
    for c in coeffs.iter().rev() {
        acc = fadd(fmul(acc, x), *c);
    }
    acc
}

/// Evaluate `coeffs` at every point of the size-`N` smooth coset generated
/// by `omega`. Naive DFT; replaceable with a real radix-2 NTT for `N ≥ 256`.
#[pyfunction]
fn poly_eval_domain(coeffs: Vec<u64>, omega: u64, n: usize) -> Vec<u64> {
    (0..n)
        .map(|i| poly_eval_native(&coeffs, fpow(omega, i as u64)))
        .collect()
}

/// One FRI folding step: `f'(Y) = f_even(Y) + α · f_odd(Y)` evaluated on
/// the squared coset of half size.
#[pyfunction]
fn fri_fold(layer: Vec<u64>, omega: u64, alpha: u64) -> Vec<u64> {
    let n = layer.len();
    let half = n / 2;
    let inv_two = finv(2);
    let omega_inv = finv(omega);
    let mut out = vec![0u64; half];
    for i in 0..half {
        let f_lo = layer[i];
        let f_hi = layer[i + half];
        let f_even = fmul(fadd(f_lo, f_hi), inv_two);
        let f_odd = fmul(
            fsub(f_lo, f_hi),
            fmul(inv_two, fpow(omega_inv, i as u64)),
        );
        out[i] = fadd(f_even, fmul(alpha, f_odd));
    }
    out
}

fn hash_with_domain(domain: &[u8], chunks: &[&[u8]]) -> [u8; 32] {
    let mut hasher = Blake2b256::new();
    hasher.update(domain);
    for c in chunks {
        hasher.update(c);
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&hasher.finalize());
    out
}

/// Compute the Merkle root over `leaves` (each a `u64` field element).
/// Layer-0 hashes the leaf bytes with the LEAF domain tag; higher layers
/// use the NODE tag. Mirrors the Python implementation byte-for-byte.
#[pyfunction]
fn merkle_root<'py>(py: Python<'py>, leaves: Vec<u64>) -> Bound<'py, PyBytes> {
    let mut n: usize = 1;
    while n < leaves.len() {
        n <<= 1;
    }
    let mut padded = leaves.clone();
    padded.resize(n, 0);
    let mut level: Vec<[u8; 32]> = padded
        .iter()
        .map(|v| hash_with_domain(LEAF_DOMAIN, &[&v.to_be_bytes()]))
        .collect();
    while level.len() > 1 {
        level = level
            .chunks_exact(2)
            .map(|pair| hash_with_domain(NODE_DOMAIN, &[&pair[0], &pair[1]]))
            .collect();
    }
    PyBytes::new_bound(py, &level[0])
}

#[pymodule]
fn zkstark_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(poly_eval_domain, m)?)?;
    m.add_function(wrap_pyfunction!(fri_fold, m)?)?;
    m.add_function(wrap_pyfunction!(merkle_root, m)?)?;
    Ok(())
}
