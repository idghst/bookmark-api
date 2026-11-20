# 맥미니 배포 이미지. DB는 공용 Postgres(project/데이터베이스)에 bookmark-internal 네트워크로 붙는다.
FROM python:3.12-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app app
USER nobody
EXPOSE 8000
# proxy(nginx) 뒤에서 X-Forwarded-* 를 믿는다. 포트는 호스트에 열지 않는다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
