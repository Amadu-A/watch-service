#!/usr/bin/env bash
# scripts/watch.sh
# Единственная инструкция для Windows/Git Bash, CI и Linux: проверки, миграции, сети и deployment.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$TASK_ROOT"
if command -v cygpath >/dev/null 2>&1; then
  export PYTHONPATH="$(cygpath -m "$TASK_ROOT/src")"
else
  export PYTHONPATH="$TASK_ROOT/src"
fi
mkdir -p .cache
if command -v id >/dev/null 2>&1; then
  export WATCH_UID="$(id -u)"
  export WATCH_GID="$(id -g)"
fi
COMPOSE=(docker compose --env-file .env.example)
if [[ -f .env ]]; then COMPOSE+=(--env-file .env); fi
COMPOSE+=(-f compose.yaml)

# Compose читает приватный .env; локальные проверки используют uv на рабочей станции.
uv_python() { uv run --no-sync python "$@"; }
compose() { "${COMPOSE[@]}" "$@"; }
build_ops() { compose --profile ops build ops; }
ops() { compose --profile ops run --rm --no-deps ops "$@"; }
sync_dependencies() {
  if ! command -v uv >/dev/null 2>&1; then
    echo 'uv нужен только для локальных проверок; установите его на рабочей станции.' >&2
    return 127
  fi
  uv sync --frozen --no-extra vision
}
discover() {
  if command -v uname >/dev/null 2>&1; then uname -a; fi
  docker version
  docker compose version
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  docker network ls
  if command -v ss >/dev/null 2>&1; then ss -lnt; fi
  if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi; fi
  if command -v free >/dev/null 2>&1; then free -h; fi
  df -h .
}
prepare_network() {
  local network_name
  network_name="$(ops value SHARED_NETWORK)"
  docker network inspect "$network_name" >/dev/null 2>&1 || docker network create "$network_name"
}
preflight() {
  [[ -f .env ]] || { echo 'Сначала выполните watch.sh init и настройте .env.'; exit 1; }
  discover
  build_ops
  ops check
  prepare_network
  compose config --quiet
}
vision_service() {
  local device
  device="$(ops value VISION_DEVICE)"
  if [[ "$device" == cpu ]]; then
    echo vision-cpu
  else
    echo vision
  fi
}
unit_tests() {
  local test_temp
  test_temp="$(mktemp -d "$TASK_ROOT/.cache/tests.XXXXXX")"
  if command -v cygpath >/dev/null 2>&1; then test_temp="$(cygpath -m "$test_temp")"; fi
  APP_ENV=testing DATABASE_ENGINE=sqlite DJANGO_SETTINGS_MODULE=config.testing \
    uv run --no-sync pytest -q --tb=short --cov=src --cov-branch -m 'not e2e' --basetemp "$test_temp"
  node --test tests/frontend/*.test.mjs
}
e2e_tests() {
  local test_temp
  test_temp="$(mktemp -d "$TASK_ROOT/.cache/e2e.XXXXXX")"
  if command -v cygpath >/dev/null 2>&1; then test_temp="$(cygpath -m "$test_temp")"; fi
  APP_ENV=testing DATABASE_ENGINE=sqlite DJANGO_SETTINGS_MODULE=config.testing RUN_E2E=true \
    uv run --no-sync pytest -q --tb=short -m e2e --basetemp "$test_temp"
}
local_check() {
  sync_dependencies
  uv run --no-sync ruff check src tests manage.py
  uv run --no-sync ruff format --check src tests manage.py
  for source in static/js/*.js static/js/components/*.js static/js/features/*.js; do node --check "$source"; done
  APP_ENV=testing DATABASE_ENGINE=sqlite uv_python manage.py check
  APP_ENV=testing DATABASE_ENGINE=sqlite uv_python manage.py makemigrations --check --dry-run
  unit_tests
  e2e_tests
}
container_tests() {
  compose --profile tests build tests
  compose --profile tests up -d --wait test-postgres test-redis
  local result=0
  compose --profile tests run --rm tests pytest -q --tb=short || result=$?
  if [[ "$result" == 0 ]]; then
    compose --profile tests run --rm tests node --test tests/frontend/layout.test.mjs || result=$?
  fi
  compose --profile tests stop test-postgres test-redis
  return "$result"
}
deploy() {
  [[ -z "$(git status --porcelain)" ]] || { echo 'Развёртывание требует чистый checkout.'; exit 1; }
  git pull --ff-only origin main
  preflight
  local vision
  local services=(web notification-worker scheduler)
  if [[ "$(ops value VISION_ENABLED)" == true ]]; then
    vision="$(vision_service)"
    services+=("$vision")
  fi
  compose build "${services[@]}"
  container_tests
  compose up -d --wait postgres redis
  compose run --rm --no-deps web python manage.py migrate --noinput
  compose --profile gpu --profile cpu stop vision vision-cpu
  compose up -d --wait --wait-timeout 180 --force-recreate "${services[@]}"
  compose --profile gpu --profile cpu ps
  compose exec -T web python -c 'import urllib.request; print(urllib.request.urlopen("http://localhost:8000/health/ready", timeout=5).read().decode())'
}

case "${1:-help}" in
  init) build_ops; ops init ;;
  discover) discover ;;
  inspect-rabbit) docker inspect --format '{{json .NetworkSettings.Networks}}' "${2:?Имя RabbitMQ container}" ;;
  rabbit) discover; build_ops; prepare_network; compose --profile ops run --rm --no-deps --user 0:0 --volume /var/run/docker.sock:/var/run/docker.sock ops rabbit "${2:?Передайте имя shared RabbitMQ container}" ;;
  model) build_ops; ops model ;;
  browsers)
    sync_dependencies
    if command -v cygpath >/dev/null 2>&1; then uv run --no-sync playwright install --no-shell chromium
    else uv run --no-sync playwright install --with-deps --no-shell chromium; fi
    ;;
  local-check) local_check ;;
  test) sync_dependencies; unit_tests ;;
  e2e) sync_dependencies; e2e_tests ;;
  format) sync_dependencies; uv run --no-sync ruff check src tests manage.py --fix; uv run --no-sync ruff format src tests manage.py ;;
  preflight) preflight ;;
  test-containers) preflight; container_tests ;;
  deploy) deploy ;;
  migrate) compose run --rm web python manage.py migrate --noinput ;;
  make-migrations) sync_dependencies; APP_ENV=testing DATABASE_ENGINE=sqlite uv_python manage.py makemigrations ;;
  admin) compose run --rm web python manage.py createsuperuser ;;
  user) compose run --rm web python manage.py create_watch_user "${2:?Имя пользователя}" "${3:?Роль пользователя}" ;;
  import-cameras) compose run --rm web python manage.py bootstrap_cameras ;;
  retention) compose exec -T web python -m infrastructure.storage.maintenance ;;
  status) compose --profile gpu --profile cpu ps ;;
  logs) compose --profile gpu --profile cpu logs --tail=100 "${2:-web}" ;;
  stop) compose --profile gpu --profile cpu stop web vision vision-cpu notification-worker scheduler ;;
  commit)
    local_check
    git add -u -- .
    git add -A -- .gitignore .gitattributes .dockerignore .env.example .python-version pyproject.toml uv.lock package.json manage.py Dockerfile compose.yaml README.md LICENSE docs-specification.md src static templates tests scripts docs .github
    git diff --cached --check
    git commit -m "${2:?Передайте сообщение коммита}"
    ;;
  push) git push origin main ;;
  *) echo 'watch.sh: init | discover | inspect-rabbit CONTAINER | rabbit CONTAINER | model | browsers | local-check | test | e2e | format | preflight | test-containers | deploy | migrate | make-migrations | admin | user NAME ROLE | import-cameras | retention | status | logs SERVICE | stop | commit MESSAGE | push' ;;
esac
