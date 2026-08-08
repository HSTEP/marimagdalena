# One process: FastAPI, serving /api, /admin and the site's own assets.
#
# The old image ran three — nginx on :3000 serving a copy of the generated site,
# a Vite dev server on :5173, and uvicorn — which is two more than the job
# needs. The generated site is what GitHub Pages already hosts, so serving a
# second copy from the container only invited the two to disagree.
#
# The image carries the Python environment, git, and the admin app compiled to
# static files. Everything else — api.py, build.py, the templates, the
# photographs — comes from the repository checkout bind-mounted at /app,
# because publishing means committing and pushing that checkout.

# --------------------------------------------------------------------------- #
# The admin app
# --------------------------------------------------------------------------- #
FROM node:22-alpine AS admin
WORKDIR /build

# The manifests first, so editing a component does not reinstall node_modules.
COPY mariadmin/package.json mariadmin/package-lock.json ./
RUN npm ci

COPY mariadmin/ ./
# `npm run build` type-checks first, so a build that succeeds here is a build
# that compiled. vite.config.ts sets base=/admin/, which is where api.py mounts
# the result.
RUN npm run build

# --------------------------------------------------------------------------- #
# The server
# --------------------------------------------------------------------------- #
FROM python:3.12-slim

# git, because a publish is a commit and a push. openssh-client, because the
# remote is git@github.com and the deploy key needs something to speak ssh.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# GitHub's host key, baked in rather than accepted on first use. The push runs
# in a background job with nobody to answer "are you sure?", so an unknown host
# has to be a failure and not a prompt.
#
# If GitHub ever rotates this — they did in March 2023 — pushes stop with a
# host-key warning and the fix is to replace the line below, from
# https://api.github.com/meta (`ssh_keys`).
RUN printf '%s\n' \
    'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
    > /etc/ssh/ssh_known_hosts

# Dependencies from the lock file, into their own environment. Not /app/.venv:
# the checkout is mounted over /app at run time and would hide it.
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /opt/src
COPY pyproject.toml uv.lock ./
# --locked, not --frozen: --frozen installs whatever the lock file says without
# checking it still matches pyproject.toml, which is how the lock came to be
# missing itsdangerous and pillow-heif — the container would have started with
# no session signing and no way to read an iPhone photograph. This fails the
# build instead. Re-lock with `uv lock`.
#
# --no-install-project: there is no package to install. The "project" is a
# checkout of a website, and its pyproject.toml exists to name dependencies.
RUN uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python3

COPY --from=admin /build/dist /opt/admin

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SITE_ROOT=/app \
    ADMIN_DIST=/opt/admin \
    MARI_HOST=0.0.0.0 \
    MARI_PORT=8000

# ssh with no home directory of its own: the key is mounted read-only, and
# IdentitiesOnly stops ssh offering anything else it happens to find.
ENV GIT_SSH_COMMAND="ssh -i /run/secrets/deploy_key -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts -o StrictHostKeyChecking=yes"

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# The server writes into the bind-mounted checkout, so it has to run as whoever
# owns it on the host — otherwise the files come out owned by root and the next
# `git pull` there cannot touch them.
#
# A build argument and a real account, rather than compose's `user:` alone: an
# unmapped uid has no entry in /etc/passwd, and ssh refuses to start at all
# without one ("No user exists for uid 1000", exit 255). That failure would show
# up as a publish that gets all the way to the push and then dies.
#
# Changing MARI_UID therefore needs `docker compose up -d --build`.
ARG MARI_UID=1000
ARG MARI_GID=1000
RUN groupadd -g "${MARI_GID}" mari || true \
    && useradd -u "${MARI_UID}" -g "${MARI_GID}" -m -d /home/mari -s /bin/sh mari
ENV HOME=/home/mari
USER mari

# The checkout is mounted here. Nothing is copied into it.
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
