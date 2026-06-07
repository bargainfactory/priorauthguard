# FHE training + compilation

This folder owns the Concrete ML training pipeline that produces the
deployable FHE circuit for `denial_risk_v0`.

Concrete ML caps at Python `< 3.13`, so the pipeline runs **inside a
container** (Python 3.12 + concrete-ml + brevitas + torch). The host
filesystem is bind-mounted; the compiled artifact lands at
`backend/.fhe_cache/denial_risk_v0.compiled` — exactly where
`FHEInferenceService` auto-loads it.

## Run it

From the repo root:

```bash
docker build -t pa-guard-fhe -f fhe-compile/Dockerfile fhe-compile
docker run --rm -v "$(pwd):/work" pa-guard-fhe
```

You should see:

```
== Training Brevitas QAT (bits=8, hidden=16, train_n=4000, calib_n=512) ==
  epoch=  0  loss=...
  ...
== Trained in ~10s ==
  train_acc=0.78  eval_acc=0.77
== Compiling to FHE circuit (concrete-ml) ==
== Compiled in ~60s ==
== Plaintext vs FHE parity check (32 samples) ==
  plaintext_subset_acc=0.78
== Artifact written: /work/backend/.fhe_cache/denial_risk_v0.compiled ==
   size=~12,000,000 bytes
```

## Activate the artifact at runtime

The runtime expects the artifact at `backend/.fhe_cache/` and the FHE
extras (`concrete-ml`, `brevitas`, `torch`) to be installed on the host
backend. Then:

```bash
export PAG_FHE_ENABLED=true
uvicorn pa_guard.api.main:app --reload
```

`fhe_pipeline.maybe_load_compiled_circuit("denial_risk_v0")` will pick
the file up automatically. `FHEInferenceResult.fhe_executed` will start
returning `True` for `denial_risk_v0` calls, and the SLO snapshot's
`fhe-coverage` SLO will move from breached to met.

## Privacy

Training uses **synthetic data only**, generated from the same joint
distribution as `fhe_pipeline._synth_calibration` and the plaintext
logistic regression in `denial_risk_model.py`. No PHI is involved at
any stage.

## Reproducibility

`SEED=1234` is the default; bump it (or `EPOCHS`, `TRAIN_SIZE`, `QUANT_BITS`)
via env vars on the `docker run`. The artifact bytes vary only with
concrete-ml's compiler version (locked in the Dockerfile to
`concrete-ml >= 1.9, < 2.0`).

## Tunable env vars

| Variable | Default | Purpose |
|---|---|---|
| `QUANT_BITS` | 8 | INT8 quantization (6–8 are sane) |
| `CALIB_SIZE` | 512 | Number of calibration samples Concrete ML sees |
| `TRAIN_SIZE` | 4000 | Plaintext training samples |
| `EPOCHS` | 120 | Adam epochs |
| `SEED` | 1234 | Determinism |
