#!/usr/bin/env bash
# main 브랜치가 바뀌었으면 재배포한다. systemd timer 가 주기적으로 호출한다.
#
# GitHub Actions 러너는 실행할 때마다 IP 가 달라서 SSH 인바운드를 열어야 하는데,
# 그러면 오늘 8080 을 닫은 의미가 없어진다. 그래서 서버가 스스로 당겨오는 방식을 쓴다.
# 인바운드 포트도, AWS 자격증명도 필요 없다.
set -euo pipefail

REPO_DIR=/home/ubuntu/backend
COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod

cd "$REPO_DIR"

git fetch --quiet origin main

local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/main)

if [ "$local_rev" = "$remote_rev" ]; then
    exit 0
fi

echo "배포 시작: ${local_rev:0:7} → ${remote_rev:0:7}"

# 서버에서 직접 수정한 게 있으면 여기서 멈춘다. 조용히 덮어쓰지 않는다.
git merge --ff-only origin/main

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

# 매번 빌드하면 dangling 이미지가 쌓여 디스크를 채운다.
docker image prune -f >/dev/null

echo "배포 완료: $(git rev-parse --short HEAD)"
