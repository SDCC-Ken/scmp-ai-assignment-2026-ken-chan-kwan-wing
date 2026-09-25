#!/usr/bin/env bash
# Put the demo back to its starting state: drop every table, reload the fictional seed data
# and delete the uploaded files.
#
#   ./scripts/reset-demo.sh [docker|local] [--yes]
#
#   docker (default)  runs the reset inside the running "api" container of the compose stack.
#                     COMPOSE_ARGS adds compose options, for example:
#                       COMPOSE_ARGS="-f docker-compose.yml -f docker-compose.ollama.yml" \
#                         ./scripts/reset-demo.sh
#   local             runs it from backend/ with uv (DATABASE_URL and UPLOAD_DIR come from the
#                     environment or the repo-root .env, like the API itself).
#   --yes, -y         do not ask for confirmation.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: ./scripts/reset-demo.sh [docker|local] [--yes]

Drops all tables of the demo database, reloads the fictional seed data and deletes the
uploaded files. Default mode: docker (the running "api" container of docker compose).

  docker   docker compose $COMPOSE_ARGS exec -T api python -m app.cli reset-demo --yes
  local    cd backend && uv run python -m app.cli reset-demo --yes

Options: --yes, -y  skip the confirmation; -h, --help  show this help.
USAGE
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

mode="docker"
assume_yes="no"
for arg in "$@"; do
  case "$arg" in
    docker | local) mode="$arg" ;;
    --yes | -y) assume_yes="yes" ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $arg"
      ;;
  esac
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$repo_root/docker-compose.yml" ] && [ -d "$repo_root/backend/app" ] ||
  die "cannot find docker-compose.yml and backend/ next to scripts/ (looked in $repo_root)."
cd "$repo_root"

if [ "$mode" = "docker" ]; then
  target="the running \"api\" container (docker compose ${COMPOSE_ARGS:-})"
else
  target="the local database (DATABASE_URL and UPLOAD_DIR of the backend settings)"
fi

if [ "$assume_yes" != "yes" ]; then
  cat <<EOF2
This will DELETE, in $target:
  - every table of the demo database (all requests, conversations, notifications, audit rows)
  - every uploaded file (receipts and sick notes)
and then reload the fictional demo data. This cannot be undone.
EOF2
  if [ ! -t 0 ]; then
    die "not a terminal, so I cannot ask. Re-run with --yes to confirm."
  fi
  read -r -p "Continue? [y/N] " reply || reply=""
  case "$reply" in
    y | Y | yes | YES) ;;
    *)
      echo "Cancelled. Nothing was changed."
      exit 0
      ;;
  esac
fi

if [ "$mode" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH. Use: ./scripts/reset-demo.sh local"
  docker info >/dev/null 2>&1 || die "docker is not running. Start Docker Desktop (or the Docker service) and try again."
  # COMPOSE_ARGS is intentionally split into words (for example "-f a.yml -f b.yml").
  # shellcheck disable=SC2086
  if ! docker compose ${COMPOSE_ARGS:-} ps --status running --services 2>/dev/null | grep -qx api; then
    die "the \"api\" container is not running. Start the stack first: docker compose up -d
       (with local AI only: COMPOSE_ARGS=\"-f docker-compose.yml -f docker-compose.ollama.yml\")
       or reset without Docker: ./scripts/reset-demo.sh local"
  fi
  # shellcheck disable=SC2086
  if ! docker compose ${COMPOSE_ARGS:-} exec -T api python -m app.cli reset-demo --yes; then
    die "the reset failed inside the container. If the message above says \"invalid choice\", the
       image is older than this command: rebuild it with  docker compose up --build -d"
  fi
else
  command -v uv >/dev/null 2>&1 || die "uv is not installed or not on PATH (see backend/README.md)."
  (cd backend && uv run python -m app.cli reset-demo --yes)
fi

echo
echo "Done. Next step: sign in at http://localhost:9180 (refresh the page if it is already open)."
