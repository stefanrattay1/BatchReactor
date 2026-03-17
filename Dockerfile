FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        coinor-libipopt-dev \
        nodejs \
        npm \
    && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY configs/ configs/
COPY recipes/ recipes/
COPY dashboard/ dashboard/
COPY frontend/ frontend/

RUN npm --prefix frontend install --no-audit --no-fund \
    && npm --prefix frontend run build

RUN pip install --no-cache-dir . && \
    pip install --no-cache-dir idaes-pse && \
    idaes get-extensions --verbose

EXPOSE 4840
EXPOSE 8000

CMD ["python", "-m", "reactor"]
