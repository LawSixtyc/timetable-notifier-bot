#!/usr/bin/env bash
set -e
docker compose up -d --build
docker compose run --rm backend pytest -q -m integration
docker compose down -v
