# Imagen de la API (para Render, Railway, Cloud Run, etc.)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api ./api
COPY etl ./etl
RUN python -m etl.limpieza
ENV PORT=8000
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT}
