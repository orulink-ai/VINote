FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

RUN set -eux; \
    packages='ffmpeg ca-certificates gcc g++ make libffi-dev libssl-dev libpq5 cargo rustc pkg-config'; \
    apt-get update -o Acquire::Retries=10; \
    for attempt in 1 2 3 4 5; do \
        if apt-get install -y --fix-missing --no-install-recommends $packages; then \
            break; \
        fi; \
        if [ "$attempt" -eq 5 ]; then \
            exit 1; \
        fi; \
        apt-get install -f -y || true; \
        sleep 5; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY main.py mcp_server.py ./

RUN useradd --create-home --shell /usr/sbin/nologin vinote \
    && mkdir -p /app/data /app/output \
    && chown -R vinote:vinote /app

USER vinote

EXPOSE 8900

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8900"]
