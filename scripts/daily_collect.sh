#!/usr/bin/env bash
# ============================================================
# 每日盤中收 tick → 收盤後產生 feature 快照
# 在 tmux 內手動啟動(凌晨啟動也可,腳本會自己等到 08:59 暖機):
#
#   tmux new -s collect
#   cd /work/u314112028/STOCK && ./scripts/daily_collect.sh
#   # 按 Ctrl+b 再按 d 離開(detach),腳本繼續跑
#
# 設計重點:
#   - 只允許 1 條 Fugle 連線 → 啟動前先 pkill 殘留 process
#   - 等到 08:59(開盤前 1 分鐘)才連線暖機
#   - 用 timeout 跑到 13:35 自動停止,不留殘留連線
#   - 週末自動跳過
# ============================================================
export TZ="Asia/Taipei"
cd /work/u314112028/STOCK || exit 1
source .venv/bin/activate

DATE="$(date +%F)"
DOW="$(date +%u)"                              # 6=六 7=日
[ "$DOW" -ge 6 ] && { echo "週末,不收集"; exit 0; }
mkdir -p logs
LOG="logs/collect_${DATE}.log"
echo "==== start $(date '+%F %T') ====" | tee -a "$LOG"

# 1. 等到 08:59(開盤前 1 分鐘暖機)
OPEN=$(( $(date -d "08:59" +%s) - $(date +%s) ))
[ "$OPEN" -gt 0 ] && { echo "等待 08:59,sleep ${OPEN}s …" | tee -a "$LOG"; sleep "$OPEN"; }

# 2. 只允許 1 條連線 → 先清殘留
pkill -f "src.main"; sleep 5

# 3. 收到 13:35 自動停(收盤 13:30 + 緩衝)
SECS=$(( $(date -d "13:35" +%s) - $(date +%s) ))
[ "$SECS" -le 0 ] && { echo "已過收盤,不收集"; exit 0; }
echo "開始收集,將於 13:35 停止 (${SECS}s)…" | tee -a "$LOG"
timeout "${SECS}s" python -m src.main --config config/config.yaml >> "$LOG" 2>&1
pkill -f "src.main"; sleep 3

# 4. 產生 features
echo "產生 features…" | tee -a "$LOG"
python -c "from src.core.config import load_config; from src.strategy.feature_pipeline import FeaturePipeline; FeaturePipeline(load_config('config/config.yaml')).run('$DATE')" >> "$LOG" 2>&1
echo "==== done $(date '+%F %T') ====" | tee -a "$LOG"
