import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml.predictor import BMTCBusPredictor
from app.core.config import settings

def main():
    start = time.time()
    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    print(f"Init: {time.time()-start:.2f}s")
    
    start = time.time()
    predictor.train()
    print(f"Train: {time.time()-start:.2f}s")
    
    start = time.time()
    res = predictor.predict("Majestic", "Electronic City", limit=6)
    print(f"Predict 1: {time.time()-start:.2f}s")
    
    start = time.time()
    res = predictor.predict("Koramangala", "Indiranagar", limit=6)
    print(f"Predict 2: {time.time()-start:.2f}s")

if __name__ == "__main__":
    main()
