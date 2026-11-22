#!/usr/bin/env bash
# Start / restart / check the whole live stack on the Mac mini (the coordinator machine).
#   tools/demo/mac_stack.sh start | restart | status | stop
# Runs from the repo root. Tokens stay in runs/coordinator/tok (never printed). Phone-fleet secrets in runs/phones/env.
# Omen side is separate: ~/digitalheat-omen-agent.sh (batch node) + the omen-gpu transcriber (see docs/DEMO-RUNBOOK.md).
set -u
cd "$(dirname "$0")/../.."
PY=.venv/bin/python; NODEPY=.venv-node/bin/python
SITE=https://dhruvs-mac-mini.tailaf7ebe.ts.net:8443
export PYTHONPATH=src
L=runs/logs; mkdir -p "$L"

kill_port() { local p; p=$(lsof -ti tcp:"$1" -sTCP:LISTEN 2>/dev/null); [ -n "$p" ] && kill -TERM $p && for _ in $(seq 20); do kill -0 $p 2>/dev/null || break; sleep 0.5; done; }
kill_pat() { pkill -f "$1" 2>/dev/null; true; }

stop() {
  kill_pat "coordinator.sitesim"; kill_pat "live_agent --coordinator http://127.0.0.1:8710"
  kill_port 8720; kill_port 8710
}

start() {
  sqlite3 runs/coordinator/state.db ".backup runs/coordinator/state.autobackup.db" 2>/dev/null
  DH_CORS_ORIGINS=$SITE nohup $PY -m coordinator --state runs/coordinator --host 127.0.0.1 --port 8710 >> runs/coordinator/coordinator.log 2>&1 < /dev/null &
  for _ in $(seq 30); do curl -s -m2 http://127.0.0.1:8710/healthz >/dev/null && break; sleep 0.5; done
  nohup $PY -m live_agent --coordinator http://127.0.0.1:8710 --node-id node-mac --token-file runs/coordinator/tok/node_node-mac \
    --eligible public,swiss-only,certified --certified > $L/agent-node-mac.log 2>&1 < /dev/null &
  [ -x $NODEPY ] && nohup $NODEPY -m live_agent --coordinator http://127.0.0.1:8710 --node-id mac-live --token-file runs/coordinator/tok/node_mac-live \
    --site-id node-mac --backend whisper-local --model small.en > $L/agent-mac-live.log 2>&1 < /dev/null &
  for s in node-omen2 node-mac; do
    nohup $PY -m coordinator.sitesim --coordinator http://127.0.0.1:8710 --token-file runs/coordinator/tok/site_$s --site $s \
      --replay coldest --speed 60 --loop --scenario-dir runs/coordinator/scenario >> $L/sitesim_$s.log 2>&1 < /dev/null &
  done
  set -a; [ -f runs/phones/env ] && . runs/phones/env; set +a
  DH_PUBLIC_SITE=$SITE DH_RUN_DIR=$PWD/runs/pitch/merit-ballast-n4-slack24.0-loadthermostat-seed0 DH_LIVE_NODES=1 \
    DH_COORDINATOR_URL=http://127.0.0.1:8710 DH_OBSERVER_TOKEN_FILE=$PWD/runs/coordinator/tok/observer \
    nohup $PY -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8720 > $L/dashboard-public.log 2>&1 < /dev/null &
  sleep 4; status
}

status() {
  echo "coordinator: $(curl -s -m3 http://127.0.0.1:8710/healthz || echo DOWN)"
  echo "public site: $(curl -s -m3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8720/ || echo DOWN)"
  echo "phone fleet: $(curl -s -m3 http://127.0.0.1:8720/api/phones/state | $PY -c 'import sys,json;d=json.load(sys.stdin);print(len(d["devices"]),"devices, join", "open" if d["join_open"] else "CLOSED")' 2>/dev/null || echo DOWN)"
  echo "processes: $(pgrep -f 'coordinator|live_agent|sitesim|dashboard.app' | wc -l | tr -d ' ') (expect 6)"
}

case "${1:-status}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  status) status ;;
  *) echo "usage: $0 start|restart|status|stop"; exit 2 ;;
esac
