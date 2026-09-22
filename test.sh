#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export ENVIRONMENT=development
export TELEMETRY_ENABLED=0
export SECRET=ThisShouldBeChangedInProduction
export ENCRYPTION_KEY=uSieBJ_695D2NA7bOPUJqFGCS2_qI8G4aI6L42WhjjM=
export GENERATED_JWK_SIZE=1024
export DATABASE_TYPE=SQLITE
export ALLOW_ORIGIN_REGEX='http://localhost:3000'
export FIEF_CLIENT_ID=FIEF_CLIENT_ID
export FIEF_CLIENT_SECRET=FIEF_CLIENT_SECRET
PYTEST_ARGS=(--no-cov)

MODE="${1:-role}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$MODE" in
  role)
    hatch run pytest tests/test_tasks_roles.py -n 0 "${PYTEST_ARGS[@]}" "$@"
    ;;
  related)
    hatch run pytest \
      tests/test_tasks_roles.py \
      tests/test_apps_api_roles.py \
      tests/test_apps_dashboard_roles.py \
      tests/test_tasks_user_roles.py \
      tests/test_services_user_roles.py \
      -n 0 \
      "${PYTEST_ARGS[@]}" "$@"
    ;;
  full)
    hatch run pytest tests/ -n auto "${PYTEST_ARGS[@]}" "$@"
    ;;
  -h|--help|help)
    cat <<'USAGE'
Usage: ./test.sh [role|related|full] [pytest args...]

  role     Run role permission propagation task regressions (default)
  related  Run role routers, user-role tasks, and role permission tests
  full     Run the complete test suite
USAGE
    ;;
  *)
    hatch run pytest "$MODE" -n 0 "${PYTEST_ARGS[@]}" "$@"
    ;;
esac
