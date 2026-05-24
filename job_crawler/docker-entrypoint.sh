#!/usr/bin/env sh
# Dispatch on the first arg:
#   api               → uvicorn job_crawler_api.app:app on :8080
#   crawler <slug>    → python -m job_crawler.cli.run <slug>  (added in phase 1)
#   schema-apply      → bootstrap: psql -f db_schema.sql via the lib
#   anything else     → execed verbatim (debug shells, one-offs)
set -eu

case "${1:-api}" in
  api)
    exec uvicorn job_crawler_api.app:app \
      --host 0.0.0.0 --port "${PORT:-8080}" \
      --proxy-headers --forwarded-allow-ips='*' \
      --no-access-log
    ;;
  crawler)
    shift
    exec python -m job_crawler.cli.run "$@"
    ;;
  canary)
    shift
    exec python -m job_crawler.cli.canary "$@"
    ;;
  discover)
    shift
    exec python -m job_crawler.cli.discover "$@"
    ;;
  intelligence)
    shift
    exec python -m job_crawler.cli.intelligence "$@"
    ;;
  schema-apply)
    exec python -c "
import asyncio, psycopg, os
from job_crawler_db import apply_schema
async def main():
    async with await psycopg.AsyncConnection.connect(os.environ['JCDB_DSN']) as c:
        await apply_schema(c)
    print('schema applied')
asyncio.run(main())
"
    ;;
  *)
    exec "$@"
    ;;
esac
