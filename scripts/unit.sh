#!/usr/bin/env bash
set -e
docker compose run --rm backend pytest -q
