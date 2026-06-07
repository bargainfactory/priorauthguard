"""Train and persist the denial-risk logistic regression.

Usage:
    python -m pa_guard.scripts.train_denial_risk
    python -m pa_guard.scripts.train_denial_risk --samples 8000 --seed 42

Writes the weights to
`pa_guard/services/denial_risk_v1.weights.json` so the runtime predictor
(`DenialRiskModel.load`) finds them without any sklearn / torch
dependency at request time.
"""
from __future__ import annotations

import argparse
import json

from pa_guard.core.logging import configure_logging, get_logger
from pa_guard.services.denial_risk_model import save_weights, train_denial_risk_v1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--epochs", type=int, default=600)
    parser.add_argument("--lr", type=float, default=0.5)
    args = parser.parse_args()

    configure_logging()
    log = get_logger("train_denial_risk")
    log.info(
        "training_starting",
        n_samples=args.samples,
        seed=args.seed,
        epochs=args.epochs,
        lr=args.lr,
    )

    model = train_denial_risk_v1(
        n_samples=args.samples,
        seed=args.seed,
        epochs=args.epochs,
        lr=args.lr,
    )
    path = save_weights(model)
    log.info(
        "training_complete",
        weights_path=str(path),
        weights=list(model.weights),
        bias=model.bias,
    )
    print(json.dumps(model.to_dict(), indent=2))


if __name__ == "__main__":
    main()
