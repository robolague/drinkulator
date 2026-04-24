FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --upgrade pip && \
    pip install uv && \
    uv sync --frozen --no-dev

COPY . .

EXPOSE 5000

CMD ["sh", "-c", ". .venv/bin/activate && exec flask --app main run --host=0.0.0.0 --port=${PORT}"]
