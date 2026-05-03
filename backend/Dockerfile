FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint native deps + build essentials + OSINT tools deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
        libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-liberation \
        curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --upgrade pip hatchling && \
    pip install -e .

# Install OSINT tools
RUN pip install --no-cache-dir \
    sherlock \
    theHarvester \
    beautifulsoup4 \
    lxml

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
