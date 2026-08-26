"""prestart -- run database migrations before the API listens.

The compose stack starts ``uvicorn`` directly, which assumes the DB
already has the latest schema. On a fresh install (or after pulling
a new image with new migrations) the API would come up against an
empty / partial database and crash on the first request.

Wrapping the entrypoint with ``prestart.sh`` means the operator
never has to remember to run ``alembic upgrade head`` themselves.
The startup sequence becomes:

    prestart.sh
        -> alembic upgrade head   (idempotent; creates missing tables/types)
        -> uvicorn app.main:app   (long-running)

Behaviour:
  * Migrations are run with the same ``DIVIDE_DB_URL`` env vars that
    uvicorn sees, so dev / staging / prod all use their own DB.
  * Exit code from ``alembic`` propagates. If migrations fail, the
    container fails to start, which is what an operator wants (a
    loud failure beats a half-broken API).
  * The script is a thin wrapper, so you can also invoke it directly
    for ``docker exec divide-api prestart.sh``.

Disable with ``DIVIDE_SKIP_MIGRATIONS=1`` for the rare case where the
DB is intentionally pinned to an older revision (e.g. downgrade tests).
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if os.environ.get("DIVIDE_SKIP_MIGRATIONS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        print("[prestart] DIVIDE_SKIP_MIGRATIONS=1, skipping alembic upgrade")
        return 0

    print("[prestart] running alembic upgrade head ...")
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd="/app",
    )
    if proc.returncode != 0:
        print(
            f"[prestart] alembic upgrade failed (rc={proc.returncode}); "
            f"refusing to start uvicorn.",
            file=sys.stderr,
        )
        return proc.returncode

    print("[prestart] starting uvicorn ...")
    # Replace this process with uvicorn so signals (SIGTERM, SIGINT)
    # propagate correctly and docker-compose's stop behaviour works
    # as expected.
    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )
    # execvp does not return on success; if it does, something is wrong.
    return 1


if __name__ == "__main__":
    sys.exit(main())