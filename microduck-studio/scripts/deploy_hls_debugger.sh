#!/usr/bin/env bash
# Deploy the community-kit HLS servo debugger to the duck's core board, following
# microduck-community-kit/software/hls_servo_debugger/README.md exactly.
#
# The debugger deliberately is NOT a systemd service and does not auto-start: it shares
# /dev/ttyS2 with robotd, and one process at a time may hold the bus. Use it for a bench
# or calibration session, then stop it and hand the bus back to robotd.
#
# Usage:
#   scripts/deploy_hls_debugger.sh <user@host> install [--stop-robotd]
#   scripts/deploy_hls_debugger.sh <user@host> start   # launch with nohup on the board
#   scripts/deploy_hls_debugger.sh <user@host> status  # health + who holds the bus
#   scripts/deploy_hls_debugger.sh <user@host> stop    # stop the tool (robotd untouched)
#
# <user@host>: the board over SSH (root@<ip>). The IP changes with the network; the
# README documents one snapshot, this script never guesses an address.
set -euo pipefail

HOST="${1:?usage: deploy_hls_debugger.sh <user@host> <install|start|stop|status> [--stop-robotd]}"
ACTION="${2:?usage: deploy_hls_debugger.sh <user@host> <install|start|stop|status> [--stop-robotd]}"
REMOTE_DIR="/opt/hls_servo_debugger"
STUDIO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KIT_DIR="$STUDIO_ROOT/../microduck-community-kit/software/hls_servo_debugger"

ssh_exec() { ssh "$HOST" "$@"; }

require_kit() {
  if [ ! -f "$KIT_DIR/hls_debugger/server.py" ]; then
    echo "缺少 $KIT_DIR —— 请先检出 microduck-community-kit 子模块" >&2
    exit 1
  fi
}

case "$ACTION" in
  install)
    require_kit
    echo "[1/4] 安装发行版依赖（板子没有 uv/pip）..."
    ssh_exec 'apt-get update -qq && apt-get install -y -qq python3-flask python3-serial'
    ssh_exec 'python3 -c "import flask, serial" && echo "依赖就绪"'
    echo "[2/4] 同步源码到 $REMOTE_DIR ..."
    rsync -av --delete --exclude '.venv' --exclude '__pycache__' "$KIT_DIR/" "$HOST:$REMOTE_DIR/"
    echo "[3/4] 离线自检（不碰硬件）..."
    ssh_exec "cd $REMOTE_DIR && python3 -m hls_debugger.selftest"
    if [ "${3:-}" = "--stop-robotd" ]; then
      echo "[4/4] 停 robotd 让出总线（不会切扭矩；机器人失去平衡控制）..."
      ssh_exec 'systemctl stop robotd && systemctl is-active robotd || true'
    else
      echo "[4/4] 跳过 robotd（用 --stop-robotd 让出总线；校准前必须停）"
    fi
    echo "完成。启动：scripts/deploy_hls_debugger.sh $HOST start"
    ;;
  start)
    echo "启动工具（nohup，退出 SSH 后继续跑；用 stop 收掉）..."
    ssh_exec "fuser -v 8765/tcp 2>/dev/null && { echo '8765 已被占用，先 stop'; exit 1; } || true"
    ssh_exec "cd $REMOTE_DIR && (nohup ./run.sh --host 0.0.0.0 --no-browser > /tmp/hls_debugger.log 2>&1 &) && sleep 3 && curl -s http://127.0.0.1:8765/api/health"
    echo
    echo "浏览器打开 http://<板子IP>:8765/  → 连接 /dev/ttyS2 @ 1Mbps"
    ;;
  stop)
    ssh_exec "fuser -k 8765/tcp 2>/dev/null || echo '工具未在运行'"
    echo "总线已释放。把 robotd 还回去：ssh $HOST 'systemctl start robotd'"
    ;;
  status)
    ssh_exec "systemctl is-active robotd; fuser -v /dev/ttyS2 8765/tcp 2>&1 | grep -v '^ ' || true; curl -s --max-time 2 http://127.0.0.1:8765/api/health || echo '工具未响应'"
    ;;
  *)
    echo "未知动作：$ACTION（install | start | stop | status）" >&2
    exit 1
    ;;
esac
