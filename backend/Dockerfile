FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/train.py ./train.py
COPY dataset ./dataset

ENV DATASET_PATH=/app/dataset/routes_cleaned.csv \
    STOP_COORDINATES_PATH=/app/dataset/stops_cleaned.csv \
    METRO_DATASET_PATH=/app/dataset/bengaluru_metro_network.csv \
    FARES_DATASET_PATH=/app/dataset/fares.json \
    METRO_PDF_PATH=/app/dataset/Metro_Map_2025_-_Bengaluru_City.pdf \
    ARTIFACT_DIR=/app/artifacts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
