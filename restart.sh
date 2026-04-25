#!/bin/bash
cd /root/durak
set -a; [ -f .env ] && source .env; set +a

WORKERS=4
BASE_PORT=8090

# Kill all existing workers
for i in $(seq 0 $((WORKERS-1))); do
    fuser -k $((BASE_PORT+i))/tcp 2>/dev/null
done
sleep 2

# Clear primary worker lock so the first worker to start wins
redis-cli -h 127.0.0.1 -p 6379 DEL durak:primary_worker 2>/dev/null

# Start each worker on its own port
for i in $(seq 0 $((WORKERS-1))); do
    PORT=$((BASE_PORT+i))
    PYTHONPATH=/root/durak PORT=$PORT DATABASE_URL="${DATABASE_URL}" nohup venv/bin/python3 -m uvicorn server.main:app \
        --host 0.0.0.0 \
        --port $PORT \
        >> server_w${i}.log 2>&1 &
    echo "worker $i → port $PORT (pid $!)"
done

sleep 3
for i in $(seq 0 $((WORKERS-1))); do
    PORT=$((BASE_PORT+i))
    printf "worker $i (port $PORT): "
    curl -s --max-time 2 http://localhost:$PORT/healthz || echo "timeout"
done
