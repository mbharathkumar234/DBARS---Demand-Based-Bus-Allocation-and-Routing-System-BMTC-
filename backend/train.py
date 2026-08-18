from __future__ import annotations

import json

from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor


if __name__ == "__main__":
    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    metrics = predictor.train(force=True)
    print(json.dumps(metrics, indent=2))
