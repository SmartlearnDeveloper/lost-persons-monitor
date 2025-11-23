#!/usr/bin/env bash
set -euo pipefail

# Launch the Flink job jar manually (useful after rebuilding artifacts).
docker compose exec jobmanager \
  /opt/flink/bin/flink run -d /opt/flink/usrlib/lost-persons-job.jar >/tmp/flink_job.log 2>&1

# Optionally tail the log for quick feedback; comment out if noisy.
tail -n 20 /tmp/flink_job.log
