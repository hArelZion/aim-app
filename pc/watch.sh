#!/usr/bin/env bash
# AIM watcher. Runs on this computer and costs no tokens: every few seconds it asks Supabase
# whether the phone sent anything, and keeps a heartbeat so the phone can show "connected".
# It exits (which wakes Claude) when there is an unread message ("AIM new") or the phone
# paused the line ("AIM stop").
# Usage: watch.sh [claude|gpt|gemini|team]  (default claude). Each model has its own conversations (ids "g..." are
# ChatGPT, "m..." Gemini; team chats "t..." go to Claude), heartbeat row and pause switch (settings.mode / mode_gpt / mode_gemini).
set -a; . "$HOME/.aim/secrets.env"; set +a
model="${1:-claude}"
case "$model" in
  gpt)    wid="watcher-gpt";    mkey="mode_gpt";    filter="sender=eq.me&conv=like.g*" ;;
  gemini) wid="watcher-gemini"; mkey="mode_gemini"; filter="sender=eq.me&conv=like.m*" ;;
  team)   wid="watcher-team";   mkey="mode";        filter="sender=eq.me&conv=like.t*&text=not.like.@claude*" ;;
  *)      wid="watcher";        mkey="mode";        filter="and=(or(and(sender.eq.me,or(conv.is.null,conv.not.like.t*,text.like.@claude*)),kind.eq.escalate,kind.eq.stop),or(conv.is.null,and(conv.not.like.g*,conv.not.like.m*)),id.not.like.mv*)" ;;
esac
auth=(-H "apikey: $SUPABASE_SERVICE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_KEY")
beat=0; pcbeat=0
while true; do
  now=$(date +%s)
  if [ $((now - beat)) -ge 30 ]; then
    curl -s -o /dev/null -X POST "$SUPABASE_URL/rest/v1/control" "${auth[@]}" \
      -H "Content-Type: application/json" -H "Prefer: resolution=merge-duplicates,return=minimal" \
      -d "{\"id\":\"$wid\",\"data\":{\"at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}}" || true
    if [ "$model" = claude ] && [ $((now - pcbeat)) -ge 60 ]; then   # battery / CPU / memory for the phone's settings sheet
      (python "$HOME/.aim/pcstat.py" >/dev/null 2>&1 &); pcbeat=$now
      (python "$HOME/.aim/aim_model.py" state >/dev/null 2>&1 &)   # model + effort for the phone's model button
    fi
    mode=$(curl -s "$SUPABASE_URL/rest/v1/control?id=eq.settings&select=data->>$mkey" "${auth[@]}" || true)
    case "$mode" in *'"off"'*) echo "AIM stop"; exit 0;; esac
    beat=$now
  fi
  if [ "$model" = claude ]; then   # the phone asked to switch model / effort: done here, no tokens
    req=$(curl -s "$SUPABASE_URL/rest/v1/control?id=eq.model-req&select=data->>at" "${auth[@]}" | tr -dc '0-9')
    if [ -n "$req" ] && [ "$req" != "$(cat "$HOME/.aim/model_req_at.seen" 2>/dev/null)" ]; then
      (python "$HOME/.aim/aim_model.py" apply >/dev/null 2>&1 &)
      echo "$req" > "$HOME/.aim/model_req_at.seen"
    fi
  fi
  if [ "$model" = claude ]; then   # the phone's refresh button in the computer panel
    preq=$(curl -s "$SUPABASE_URL/rest/v1/control?id=eq.pc-req&select=data->>at" "${auth[@]}" | tr -dc '0-9')
    if [ -n "$preq" ] && [ "$preq" != "$(cat "$HOME/.aim/pc_req_at.seen" 2>/dev/null)" ]; then
      echo "$preq" > "$HOME/.aim/pc_req_at.seen"
      (python "$HOME/.aim/pcstat.py" "req=$preq" >/dev/null 2>&1 &); pcbeat=$now
    fi
  fi
  r=$(curl -s "$SUPABASE_URL/rest/v1/messages?select=id&seen=is.false&$filter" "${auth[@]}" || echo "[]")
  case "$r" in "["*"]") ;; *) r="[]";; esac
  if [ "$r" != "[]" ]; then echo "AIM new $r"; exit 0; fi
  sleep 1
done
