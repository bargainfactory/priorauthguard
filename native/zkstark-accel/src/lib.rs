//! Full FRI prover + verifier (Goldilocks field) in native Rust.
//!
//! Exposes the same public contract as `backend/pa_guard/services/zkstark.py`:
//!
//! - `poly_eval_domain(coeffs, omega, N)`
//! - `fri_fold(layer, omega, alpha)`
//! - `merkle_root(leaves)`
//! - `prove(model_commitment, input_hash, output_hash) -> bytes`
//! - `verify(model_commitment, input_hash, output_hash, proof_blob) -> bool`
//!
//! The two new entry points produce **byte-for-byte identical proofs** to
//! the Python implementation so the existing test suite passes against
//! either backend without modification. The Python shim at
//! `pa_guard/services/zkstark_native.py` consults the `HAS_NATIVE_*`
//! capability flags and dispatches the entire prove/verify cycle into Rust
//! when available, falling back to pure Python otherwise.

use blake2::digest::consts::{U16, U32, U64};
use blake2::{Blake2b, Digest};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

// ===========================================================================
// Goldilocks field
// ===========================================================================

const P: u128 = (1u128 << 64) - (1u128 << 32) + 1;
const GENERATOR: u64 = 7;
const LEAF_DOMAIN: &[u8] = b"\x00leaf";
const NODE_DOMAIN: &[u8] = b"\x01node";

const TRACE_DEGREE: usize = 4;
const BLOWUP_FACTOR: usize = 4;
const DOMAIN_SIZE: usize = TRACE_DEGREE * BLOWUP_FACTOR;
const N_QUERIES: usize = 25;
const PUBLIC_POINTS: [u64; 3] = [0, 1, 2];
const DOMAIN_SEP: &[u8] = b"pa-guard/zkstark/v2";

type Blake2b256 = Blake2b<U32>;
type Blake2b512 = Blake2b<U64>;
type Blake2b128 = Blake2b<U16>;

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

fn primitive_nth_root(n: u64) -> u64 {
    fpow(GENERATOR, ((P as u64).wrapping_sub(1)) / n)
}

// ===========================================================================
// Polynomial helpers
// ===========================================================================

fn poly_eval(coeffs: &[u64], x: u64) -> u64 {
    let mut acc: u64 = 0;
    for c in coeffs.iter().rev() {
        acc = fadd(fmul(acc, x), *c);
    }
    acc
}

fn poly_eval_domain_inner(coeffs: &[u64], omega: u64, n: usize) -> Vec<u64> {
    (0..n)
        .map(|i| poly_eval(coeffs, fpow(omega, i as u64)))
        .collect()
}

fn poly_mul(a: &[u64], b: &[u64]) -> Vec<u64> {
    let mut out = vec![0u64; a.len() + b.len() - 1];
    for (i, &ai) in a.iter().enumerate() {
        if ai == 0 {
            continue;
        }
        for (j, &bj) in b.iter().enumerate() {
            out[i + j] = fadd(out[i + j], fmul(ai, bj));
        }
    }
    out
}

fn lagrange_interpolate(xs: &[u64], ys: &[u64]) -> Vec<u64> {
    let n = xs.len();
    assert_eq!(n, ys.len());
    let mut coeffs = vec![0u64; n];
    for i in 0..n {
        let mut num: Vec<u64> = vec![1];
        let mut denom: u64 = 1;
        for j in 0..n {
            if j == i {
                continue;
            }
            num = poly_mul(&num, &[fsub(0, xs[j]), 1]);
            denom = fmul(denom, fsub(xs[i], xs[j]));
        }
        let inv_denom = finv(denom);
        let scale = fmul(ys[i], inv_denom);
        for (k, c) in num.iter().enumerate() {
            coeffs[k] = fadd(coeffs[k], fmul(*c, scale));
        }
    }
    coeffs
}

// ===========================================================================
// Hash + Merkle (uniform 32-byte digests, domain-separated)
// ===========================================================================

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

fn hash_empty() -> [u8; 32] {
    let mut hasher = Blake2b256::new();
    hasher.update(b"");
    let mut out = [0u8; 32];
    out.copy_from_slice(&hasher.finalize());
    out
}

struct MerkleTree {
    levels: Vec<Vec<[u8; 32]>>,
    padded: Vec<u64>,
}

impl MerkleTree {
    fn new(leaves: &[u64]) -> Self {
        let mut n: usize = 1;
        while n < leaves.len() {
            n <<= 1;
        }
        let mut padded = leaves.to_vec();
        padded.resize(n, 0);
        let leaf_hashes: Vec<[u8; 32]> = padded
            .iter()
            .map(|v| hash_with_domain(LEAF_DOMAIN, &[&v.to_be_bytes()]))
            .collect();
        let mut levels: Vec<Vec<[u8; 32]>> = vec![leaf_hashes];
        while levels.last().unwrap().len() > 1 {
            let prev = levels.last().unwrap();
            let next: Vec<[u8; 32]> = prev
                .chunks_exact(2)
                .map(|pair| hash_with_domain(NODE_DOMAIN, &[&pair[0], &pair[1]]))
                .collect();
            levels.push(next);
        }
        MerkleTree { levels, padded }
    }

    fn root(&self) -> [u8; 32] {
        self.levels.last().unwrap()[0]
    }

    /// Returns (leaf_value, leaf_index_u32, siblings).
    fn open(&self, index: usize) -> (u64, u32, Vec<[u8; 32]>) {
        let mut siblings: Vec<[u8; 32]> = Vec::new();
        let mut i = index;
        for level in &self.levels[..self.levels.len() - 1] {
            let sib_idx = i ^ 1;
            let sibling = if sib_idx < level.len() {
                level[sib_idx]
            } else {
                hash_empty()
            };
            siblings.push(sibling);
            i /= 2;
        }
        (self.padded[index], index as u32, siblings)
    }
}

fn merkle_verify_path(root: &[u8; 32], leaf: u64, index: usize, siblings: &[[u8; 32]]) -> bool {
    let mut cur = hash_with_domain(LEAF_DOMAIN, &[&leaf.to_be_bytes()]);
    let mut i = index;
    for sib in siblings {
        let (left, right) = if i % 2 == 0 { (&cur, sib) } else { (sib, &cur) };
        cur = hash_with_domain(NODE_DOMAIN, &[left.as_ref(), right.as_ref()]);
        i /= 2;
    }
    &cur == root
}

// ===========================================================================
// Fiat-Shamir transcript — matches the Python byte protocol exactly.
// ===========================================================================

struct Transcript {
    state: Blake2b512,
}

impl Transcript {
    fn new() -> Self {
        let mut t = Transcript { state: Blake2b512::new() };
        let mut prefix = vec![0u8];
        prefix.extend_from_slice(DOMAIN_SEP);
        t.state.update(&prefix);
        t
    }

    fn absorb(&mut self, label: &[u8], data: &[u8]) {
        self.state.update([0x01u8]);
        self.state.update((label.len() as u32).to_be_bytes());
        self.state.update(label);
        self.state.update((data.len() as u32).to_be_bytes());
        self.state.update(data);
    }

    fn digest_no_consume(&self) -> [u8; 64] {
        let cloned = self.state.clone();
        let mut out = [0u8; 64];
        out.copy_from_slice(&cloned.finalize());
        out
    }

    fn challenge_field(&mut self, label: &[u8]) -> u64 {
        self.state.update([0x02u8]);
        self.state.update(label);
        let raw = self.digest_no_consume();
        self.state.update(raw);
        let mut v: u128 = 0;
        for &b in &raw[..16] {
            v = (v << 8) | b as u128;
        }
        (v % P) as u64
    }

    fn challenge_index(&mut self, label: &[u8], modulus: u64) -> u64 {
        self.state.update([0x03u8]);
        self.state.update(label);
        let raw = self.digest_no_consume();
        self.state.update(raw);
        let mut v: u64 = 0;
        for &b in &raw[..8] {
            v = (v << 8) | b as u64;
        }
        v % modulus.max(1)
    }
}

// ===========================================================================
// FRI fold (one round)
// ===========================================================================

fn fri_fold_inner(layer: &[u64], omega: u64, alpha: u64) -> Vec<u64> {
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

// ===========================================================================
// Statement → secret polynomial
// ===========================================================================

fn hash_to_field(s: &str) -> u64 {
    let mut hasher = Blake2b128::new();
    hasher.update(s.as_bytes());
    let digest = hasher.finalize();
    let mut v: u128 = 0;
    for &b in &digest[..] {
        v = (v << 8) | b as u128;
    }
    (v % P) as u64
}

fn build_secret_polynomial(model_commitment: &str, input_hash: &str, output_hash: &str) -> Vec<u64> {
    let public = [
        hash_to_field(input_hash),
        hash_to_field(model_commitment),
        hash_to_field(output_hash),
    ];
    let witness_seed = format!(
        "{}::witness::{}::{}",
        model_commitment, input_hash, output_hash
    );
    let witness = hash_to_field(&witness_seed);
    let xs: Vec<u64> = vec![0, 1, 2, 3];
    let ys: Vec<u64> = vec![public[0], public[1], public[2], witness];
    lagrange_interpolate(&xs, &ys)
}

fn absorb_statement(t: &mut Transcript, model_commitment: &str, input_hash: &str, output_hash: &str) {
    t.absorb(b"model", model_commitment.as_bytes());
    t.absorb(b"input", input_hash.as_bytes());
    t.absorb(b"output", output_hash.as_bytes());
}

// ===========================================================================
// Proof serialization
// ===========================================================================

fn write_u32(out: &mut Vec<u8>, v: u32) {
    out.extend_from_slice(&v.to_be_bytes());
}

fn write_u64(out: &mut Vec<u8>, v: u64) {
    out.extend_from_slice(&v.to_be_bytes());
}

fn write_path(out: &mut Vec<u8>, leaf: u64, leaf_index: u32, siblings: &[[u8; 32]]) {
    write_u64(out, leaf);
    write_u32(out, leaf_index);
    write_u32(out, siblings.len() as u32);
    for s in siblings {
        out.extend_from_slice(s);
    }
}

struct ParsedPath {
    leaf: u64,
    leaf_index: u32,
    siblings: Vec<[u8; 32]>,
}

fn read_path(blob: &[u8], i: &mut usize) -> Result<ParsedPath, String> {
    if *i + 8 + 4 + 4 > blob.len() {
        return Err("path header out of range".into());
    }
    let leaf = u64::from_be_bytes(blob[*i..*i + 8].try_into().unwrap());
    *i += 8;
    let leaf_index = u32::from_be_bytes(blob[*i..*i + 4].try_into().unwrap());
    *i += 4;
    let n_sib = u32::from_be_bytes(blob[*i..*i + 4].try_into().unwrap()) as usize;
    *i += 4;
    if *i + 32 * n_sib > blob.len() {
        return Err("siblings out of range".into());
    }
    let mut siblings = Vec::with_capacity(n_sib);
    for _ in 0..n_sib {
        let mut s = [0u8; 32];
        s.copy_from_slice(&blob[*i..*i + 32]);
        *i += 32;
        siblings.push(s);
    }
    Ok(ParsedPath { leaf, leaf_index, siblings })
}

// ===========================================================================
// PyO3 hot-loop primitives (kept for the v1.0.1 partial-acceleration shim).
// ===========================================================================

#[pyfunction]
fn poly_eval_domain(coeffs: Vec<u64>, omega: u64, n: usize) -> Vec<u64> {
    poly_eval_domain_inner(&coeffs, omega, n)
}

#[pyfunction]
fn fri_fold(layer: Vec<u64>, omega: u64, alpha: u64) -> Vec<u64> {
    fri_fold_inner(&layer, omega, alpha)
}

#[pyfunction]
fn merkle_root<'py>(py: Python<'py>, leaves: Vec<u64>) -> Bound<'py, PyBytes> {
    let tree = MerkleTree::new(&leaves);
    PyBytes::new_bound(py, &tree.root())
}

// ===========================================================================
// Full prove / verify
// ===========================================================================

#[pyfunction]
fn prove<'py>(
    py: Python<'py>,
    model_commitment: &str,
    input_hash: &str,
    output_hash: &str,
) -> PyResult<Bound<'py, PyBytes>> {
    let poly = build_secret_polynomial(model_commitment, input_hash, output_hash);
    let omega = primitive_nth_root(DOMAIN_SIZE as u64);
    let mut layer = poly_eval_domain_inner(&poly, omega, DOMAIN_SIZE);

    let mut t = Transcript::new();
    absorb_statement(&mut t, model_commitment, input_hash, output_hash);

    let mut roots: Vec<[u8; 32]> = Vec::new();
    let mut trees: Vec<MerkleTree> = Vec::new();
    let mut layers: Vec<Vec<u64>> = Vec::new();
    let mut omegas: Vec<u64> = Vec::new();
    let mut cur_omega = omega;

    loop {
        let tree = MerkleTree::new(&layer);
        roots.push(tree.root());
        trees.push(tree);
        omegas.push(cur_omega);
        let len = layer.len();
        layers.push(layer);
        t.absorb(b"layer_root", &roots.last().unwrap()[..]);
        if len == 1 {
            break;
        }
        let alpha = t.challenge_field(b"alpha");
        let next = fri_fold_inner(layers.last().unwrap(), cur_omega, alpha);
        cur_omega = fmul(cur_omega, cur_omega);
        layer = next;
    }

    let final_value = layers.last().unwrap()[0];
    t.absorb(b"final", &final_value.to_be_bytes());

    let mut layer_queries: Vec<Vec<(u32, u32, ParsedPath, ParsedPath)>> = Vec::new();
    for q in 0..N_QUERIES {
        let mut label = b"q".to_vec();
        label.extend_from_slice(&(q as u16).to_be_bytes());
        let pos = t.challenge_index(&label, DOMAIN_SIZE as u64);
        let mut opens: Vec<(u32, u32, ParsedPath, ParsedPath)> = Vec::new();
        for level in 0..layers.len() - 1 {
            let size = layers[level].len();
            let half = size / 2;
            let actual_pos = (pos as usize) % size;
            let sister_pos = (actual_pos + half) % size;
            let (leaf, idx, sibs) = trees[level].open(actual_pos);
            let pos_path = ParsedPath { leaf, leaf_index: idx, siblings: sibs };
            let (sleaf, sidx, ssibs) = trees[level].open(sister_pos);
            let sister_path = ParsedPath { leaf: sleaf, leaf_index: sidx, siblings: ssibs };
            opens.push((actual_pos as u32, sister_pos as u32, pos_path, sister_path));
        }
        layer_queries.push(opens);
    }

    let mut out: Vec<u8> = Vec::with_capacity(256);
    out.extend_from_slice(b"PAGF1");
    write_u32(&mut out, roots.len() as u32);
    for r in &roots {
        out.extend_from_slice(r);
    }
    write_u32(&mut out, layer_queries.len() as u32);
    for query in &layer_queries {
        write_u32(&mut out, query.len() as u32);
        for (pos, sister_pos, pos_path, sister_path) in query {
            write_u32(&mut out, *pos);
            write_u32(&mut out, *sister_pos);
            write_path(&mut out, pos_path.leaf, pos_path.leaf_index, &pos_path.siblings);
            write_path(&mut out, sister_path.leaf, sister_path.leaf_index, &sister_path.siblings);
        }
    }
    write_u64(&mut out, final_value);
    Ok(PyBytes::new_bound(py, &out))
}

#[pyfunction]
fn verify(
    model_commitment: &str,
    input_hash: &str,
    output_hash: &str,
    proof_blob: &[u8],
) -> PyResult<bool> {
    if proof_blob.len() < 5 || &proof_blob[..5] != b"PAGF1" {
        return Ok(false);
    }
    let mut i: usize = 5;

    if i + 4 > proof_blob.len() {
        return Ok(false);
    }
    let n_roots = u32::from_be_bytes(proof_blob[i..i + 4].try_into().unwrap()) as usize;
    i += 4;
    if n_roots == 0 || i + 32 * n_roots > proof_blob.len() {
        return Ok(false);
    }
    let mut roots: Vec<[u8; 32]> = Vec::with_capacity(n_roots);
    for _ in 0..n_roots {
        let mut r = [0u8; 32];
        r.copy_from_slice(&proof_blob[i..i + 32]);
        i += 32;
        roots.push(r);
    }

    if i + 4 > proof_blob.len() {
        return Ok(false);
    }
    let n_queries = u32::from_be_bytes(proof_blob[i..i + 4].try_into().unwrap()) as usize;
    i += 4;
    let mut queries: Vec<Vec<(u32, u32, ParsedPath, ParsedPath)>> = Vec::with_capacity(n_queries);
    for _ in 0..n_queries {
        if i + 4 > proof_blob.len() {
            return Ok(false);
        }
        let n_opens = u32::from_be_bytes(proof_blob[i..i + 4].try_into().unwrap()) as usize;
        i += 4;
        let mut layer_queries: Vec<(u32, u32, ParsedPath, ParsedPath)> = Vec::with_capacity(n_opens);
        for _ in 0..n_opens {
            if i + 8 > proof_blob.len() {
                return Ok(false);
            }
            let pos = u32::from_be_bytes(proof_blob[i..i + 4].try_into().unwrap());
            i += 4;
            let sister_pos = u32::from_be_bytes(proof_blob[i..i + 4].try_into().unwrap());
            i += 4;
            let pos_path = match read_path(proof_blob, &mut i) {
                Ok(p) => p,
                Err(_) => return Ok(false),
            };
            let sister_path = match read_path(proof_blob, &mut i) {
                Ok(p) => p,
                Err(_) => return Ok(false),
            };
            layer_queries.push((pos, sister_pos, pos_path, sister_path));
        }
        queries.push(layer_queries);
    }

    if i + 8 > proof_blob.len() {
        return Ok(false);
    }
    let final_value = u64::from_be_bytes(proof_blob[i..i + 8].try_into().unwrap());

    // Statement binding.
    let secret = build_secret_polynomial(model_commitment, input_hash, output_hash);
    let public = [
        hash_to_field(input_hash),
        hash_to_field(model_commitment),
        hash_to_field(output_hash),
    ];
    for (pt, expected) in PUBLIC_POINTS.iter().zip(public.iter()) {
        if poly_eval(&secret, *pt) != *expected {
            return Ok(false);
        }
    }
    let omega = primitive_nth_root(DOMAIN_SIZE as u64);
    let base_layer = poly_eval_domain_inner(&secret, omega, DOMAIN_SIZE);
    let expected_base_root = MerkleTree::new(&base_layer).root();
    if expected_base_root != roots[0] {
        return Ok(false);
    }

    // Replay transcript.
    let mut t = Transcript::new();
    absorb_statement(&mut t, model_commitment, input_hash, output_hash);
    let mut alphas: Vec<u64> = Vec::with_capacity(roots.len().saturating_sub(1));
    for (idx, root) in roots.iter().enumerate() {
        t.absorb(b"layer_root", root);
        if idx + 1 < roots.len() {
            alphas.push(t.challenge_field(b"alpha"));
        }
    }
    t.absorb(b"final", &final_value.to_be_bytes());

    let mut omegas: Vec<u64> = Vec::with_capacity(roots.len());
    omegas.push(omega);
    for _ in 0..roots.len().saturating_sub(1) {
        let prev = *omegas.last().unwrap();
        omegas.push(fmul(prev, prev));
    }

    for (q_idx, layer_query) in queries.iter().enumerate() {
        let mut label = b"q".to_vec();
        label.extend_from_slice(&(q_idx as u16).to_be_bytes());
        let expected_pos = t.challenge_index(&label, DOMAIN_SIZE as u64);
        if layer_query.is_empty() {
            return Ok(false);
        }
        let mut pos = expected_pos as usize;
        for (level, (lq_pos, lq_sister, pos_path, sister_path)) in layer_query.iter().enumerate() {
            let level_size = DOMAIN_SIZE >> level;
            let half = level_size / 2;
            let actual_pos = pos % level_size;
            let sister_pos = (actual_pos + half) % level_size;
            if *lq_pos as usize != actual_pos || *lq_sister as usize != sister_pos {
                return Ok(false);
            }
            if !merkle_verify_path(
                &roots[level], pos_path.leaf, pos_path.leaf_index as usize, &pos_path.siblings,
            ) {
                return Ok(false);
            }
            if !merkle_verify_path(
                &roots[level], sister_path.leaf, sister_path.leaf_index as usize, &sister_path.siblings,
            ) {
                return Ok(false);
            }
            let f_lo = pos_path.leaf;
            let f_hi = sister_path.leaf;
            let inv_two = finv(2);
            let omega_inv = finv(omegas[level]);
            let f_even = fmul(fadd(f_lo, f_hi), inv_two);
            let f_odd = fmul(
                fsub(f_lo, f_hi),
                fmul(inv_two, fpow(omega_inv, actual_pos as u64)),
            );
            let derived_next = fadd(f_even, fmul(alphas[level], f_odd));
            let next_level = level + 1;
            if next_level < layer_query.len() {
                if layer_query[next_level].2.leaf != derived_next {
                    return Ok(false);
                }
            } else if derived_next != final_value {
                return Ok(false);
            }
            pos = actual_pos % (level_size / 2);
        }
    }
    Ok(true)
}

#[pyfunction]
fn _selftest() -> PyResult<bool> {
    let m = "denial_risk_v0";
    let i = "a".repeat(64);
    let o = "b".repeat(64);
    let poly = build_secret_polynomial(m, &i, &o);
    if poly.len() != 4 {
        return Err(PyValueError::new_err("secret poly must be degree-<4"));
    }
    let n = DOMAIN_SIZE as u64;
    let omega = primitive_nth_root(n);
    if fpow(omega, n) != 1 {
        return Err(PyValueError::new_err("omega^n != 1"));
    }
    if fpow(omega, n / 2) == 1 {
        return Err(PyValueError::new_err("omega is not primitive"));
    }
    Ok(true)
}

#[pymodule]
fn zkstark_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(poly_eval_domain, m)?)?;
    m.add_function(wrap_pyfunction!(fri_fold, m)?)?;
    m.add_function(wrap_pyfunction!(merkle_root, m)?)?;
    m.add_function(wrap_pyfunction!(prove, m)?)?;
    m.add_function(wrap_pyfunction!(verify, m)?)?;
    m.add_function(wrap_pyfunction!(_selftest, m)?)?;
    Ok(())
}
