FROM python:3.13-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 --user-group --shell /bin/sh appuser && \
    install -d -m 0700 -o appuser -g appuser /home/appuser/.ssh
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts/manage_staging_activation.py ./scripts/manage_staging_activation.py
COPY scripts/verify_staging_runtime.py ./scripts/verify_staging_runtime.py
RUN python -m pip install --no-cache-dir .

USER appuser
CMD ["python", "-m", "nla_catalog_gateway.runtime_bootstrap"]
