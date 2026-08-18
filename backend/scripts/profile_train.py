import time
import sys
from pathlib import Path

# Add backend directory to sys.path if needed
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml.predictor import BMTCBusPredictor
from app.core.config import settings

def main():
    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    start = time.time()
    
    # from train():
    predictor.routes = __import__('app.ml.data_loader', fromlist=['load_routes']).load_routes(predictor.dataset_path)
    print(f"load_routes: {time.time()-start:.2f}s"); start = time.time()
    
    documents = [route.document for route in predictor.routes]
    predictor.tfidf.fit(documents)
    print(f"tfidf: {time.time()-start:.2f}s"); start = time.time()
    
    predictor.profile = __import__('app.ml.data_loader', fromlist=['dataset_profile']).dataset_profile(predictor.routes)
    predictor.stop_names = sorted({stop for route in predictor.routes for stop in route.stops})
    predictor.destination_names = sorted({route.destination for route in predictor.routes if route.destination})
    # Call train()'s own builder rather than re-deriving the stop-name indexes
    # here: this script had its own copy of that line, so it kept profiling a
    # stale index shape after train() changed.
    predictor._build_stop_name_indexes()
    predictor.stop_to_route_indices = {}
    for index, route in enumerate(predictor.routes):
        for stop in route.normalized_stops:
            predictor.stop_to_route_indices.setdefault(stop, set()).add(index)
    print(f"basic_setup: {time.time()-start:.2f}s"); start = time.time()
    
    predictor.stop_pair_to_segments = predictor._build_stop_pair_index()
    print(f"build_stop_pair: {time.time()-start:.2f}s"); start = time.time()
    
    predictor.metrics = predictor._evaluate_models()
    print(f"evaluate_models: {time.time()-start:.2f}s"); start = time.time()

if __name__ == "__main__":
    main()
