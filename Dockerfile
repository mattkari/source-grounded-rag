# Source-Grounded Research Assistant — web UI, built to run continuously
# on a Raspberry Pi (arm64) or any amd64 host.
#
# The index is committed to the repository, so this image is self-contained:
# it never ingests a PDF and never needs the source document at run time.
# Credentials are NEVER baked in — they arrive from the environment at run
# time (see compose.yaml), because anything set with ENV or ARG here would be
# readable by anyone who can run `docker history`.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/app \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Unprivileged user. Streamlit wants a writable HOME for its own state.
RUN useradd --create-home --home-dir /home/app --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies first, so a code change does not re-resolve the wheel set.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R app:app /app /home/app

USER app

EXPOSE 8501

# Streamlit's own health endpoint; curl is not installed, so ask Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py"]
