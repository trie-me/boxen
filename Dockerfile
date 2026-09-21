FROM node:24.6.0-bookworm-slim@sha256:9b741b28148b0195d62fa456ed84dd6c953c1f17a3761f3e6e6797a754d9edff AS web-build
WORKDIR /src/frontend
RUN npm install --global pnpm@11.19.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8 AS python-build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.1
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
COPY backend/boxen ./backend/boxen
COPY --from=web-build /src/backend/boxen/static ./backend/boxen/static
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8
LABEL org.opencontainers.image.title="Boxen" org.opencontainers.image.version="0.1.0"
RUN groupadd --gid 10001 boxen && useradd --uid 10001 --gid 10001 --create-home boxen && mkdir -p /var/lib/boxen && chown 10001:10001 /var/lib/boxen
COPY --from=python-build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BOXEN_DATA_DIR=/var/lib/boxen
WORKDIR /app
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["boxen"]
CMD ["web", "--host", "0.0.0.0"]
