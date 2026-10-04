# Container image of the CLI: docker run --rm ghcr.io/viache25/azure-waste-finder --demo
# Base image pinned by digest; Dependabot (docker ecosystem) proposes new digests.

# Build stage: build the wheel and install it with its dependencies into a venv.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d AS build
# .git is not in the build context, so setuptools-scm gets the version from here (cd.yml passes the real one).
ARG VERSION=0.0.0+docker
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION} \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-deps --wheel-dir /wheels . \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install /wheels/*.whl

# Runtime stage: the venv only, no build tools, non-root user.
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ARG VERSION=0.0.0+docker
LABEL org.opencontainers.image.title="azure-waste-finder" \
      org.opencontainers.image.description="Find wasted spend in Azure and put a euro amount on it (read-only)" \
      org.opencontainers.image.source="https://github.com/viache25/azure-waste-finder" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
RUN useradd --create-home --uid 10001 --user-group finder
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 10001:10001
# Reports go to ./reports and the price cache to ./.cache, i.e. below /home/finder.
WORKDIR /home/finder
ENTRYPOINT ["waste-finder"]
CMD ["--help"]
