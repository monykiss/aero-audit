# aero-audit: offline demo image. Non-root, hash-pinned dependencies, no package build step.
#
#   docker build -t aero-audit .
#   docker run --rm -p 127.0.0.1:8787:8787 aero-audit          # then open http://127.0.0.1:8787
#
# The container binds 0.0.0.0 inside its own network namespace; publish the port on 127.0.0.1 (as
# above, or via compose.yaml) so only the host can reach it. To expose it on a LAN instead, drop
# --allow-unauthenticated and set AERO_APP_TOKEN.
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app AERO_HTTP_BACKEND=httpx

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin aero
WORKDIR /app

# Third-party code: every wheel verified against requirements.lock.txt (SHA-256).
COPY requirements.lock.txt ./
RUN pip install --require-hashes -r requirements.lock.txt

# First-party code and the data the demo needs. No build backend is fetched: the package runs from source.
COPY aero_audit ./aero_audit
COPY docs ./docs
COPY README.md LICENSE SECURITY.md ./
COPY data/samples ./data/samples
COPY data/watchlist.example.json ./data/
COPY models/evaluation.json models/kinematic_iforest.md ./models/
RUN mkdir -p data/recordings data/app reports logs models && chown -R aero:aero /app

USER aero
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/v1/app', timeout=4).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "aero_audit.cli"]
CMD ["demo", "--host", "0.0.0.0", "--allow-unauthenticated", "--no-open"]
