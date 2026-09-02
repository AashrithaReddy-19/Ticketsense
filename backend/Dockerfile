FROM python:3.12-slim
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY backend/pyproject.toml /workspace/backend/pyproject.toml
COPY backend/app/__init__.py /workspace/backend/app/__init__.py
WORKDIR /workspace/backend
RUN pip install --timeout 300 --retries 10 --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --timeout 300 --retries 10 --no-cache-dir ".[dev,rag]" asyncpg python-dotenv
WORKDIR /workspace
COPY backend /workspace/backend
COPY ai /workspace/ai
COPY db /workspace/db
COPY data /workspace/data
WORKDIR /workspace/backend
ENV PYTHONPATH=/workspace/backend:/workspace
CMD ["sh", "-c", "alembic upgrade head && python ../db/seed/run_seed.py && python ../db/seed/load_knowledge_base.py && python ../data/synthetic_labeled_tickets.py && (test -f ../ai/models/artifacts/department_classifier.joblib || python ../ai/models/train_classifier.py) && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
