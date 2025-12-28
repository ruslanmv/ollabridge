FROM python:3.11-slim

WORKDIR /app

# System deps for uvicorn[standard]
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src

RUN pip install -U pip && pip install .

EXPOSE 11343

CMD ["python", "-m", "uvicorn", "ollabridge.api.main:app", "--host", "0.0.0.0", "--port", "11343"]
