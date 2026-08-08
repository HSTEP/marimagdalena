#!/bin/sh
#
# Everything that has to be true before api.py can publish, checked here rather
# than discovered halfway through a push.

set -eu

SITE_ROOT="${SITE_ROOT:-/app}"
cd "$SITE_ROOT"

# git refuses to work in a repository owned by somebody else, and the checkout
# belongs to whoever owns it on the host. The compose file maps the container's
# user to that owner so the files stay writable; this covers the case where the
# mapping is wrong or absent, so the failure is a permissions error on a write
# rather than an unrelated-looking "dubious ownership" on every git call.
#
# Passed through the environment instead of `git config --global`, because
# there is no home directory to write it into.
GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0="$SITE_ROOT"
export GIT_CONFIG_COUNT GIT_CONFIG_KEY_0 GIT_CONFIG_VALUE_0

if [ ! -d "$SITE_ROOT/.git" ]; then
    echo "  ! $SITE_ROOT is not a git checkout." >&2
    echo "    Mount the repository there — drafts and publishing are both git." >&2
    exit 1
fi

if [ ! -r /run/secrets/deploy_key ]; then
    # Not fatal. She can still edit, and her work waits as drafts; only the
    # push at the end of a publish will fail, and it says so in Czech.
    echo "  ! /run/secrets/deploy_key is missing — publishing will fail at the push."
else
    # ssh ignores a key anyone else can read. A read-only bind mount keeps the
    # host's permissions, so this is a check and not a chmod.
    case "$(stat -c '%a' /run/secrets/deploy_key)" in
        400|600) ;;
        *) echo "  ! /run/secrets/deploy_key is readable by others; ssh will refuse it." ;;
    esac
fi

# Deliberately no build at startup. The generated HTML is committed — GitHub
# Pages serves it straight from the repository — so there is nothing to
# regenerate, and building on every restart would rewrite committed files
# before anyone had asked for anything.

# `python api.py` rather than `uvicorn api:app`, for the configuration checks it
# prints on the way up. Whether the password hash is set is the sort of thing
# worth reading in `docker logs` and not at the login screen.
exec python api.py
