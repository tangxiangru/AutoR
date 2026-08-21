#!/bin/bash
# Throwaway probe: read memory_paths + mcp_servers out of the init record.
# $1 = label, $2 = cwd, rest = extra claude args
label="$1"; shift
wd="$1"; shift
out="/tmp/lens3_${label}.jsonl"
cd "$wd" || exit 1
timeout 300 claude --model opus \
  "$@" -p 'Reply with exactly: OK' --output-format stream-json --verbose \
  > "$out" 2>/tmp/lens3_${label}.err
echo "=== $label (cwd=$wd) rc=$? ==="
python3 - "$out" <<'PY'
import json,sys
p=sys.argv[1]
try:
    line=open(p).readline()
    d=json.loads(line)
except Exception as e:
    print("  PARSE FAIL:", e); print(open(p).read()[:600]); sys.exit()
print("  type/subtype:", d.get("type"), d.get("subtype"))
print("  has memory_paths key:", "memory_paths" in d)
print("  memory_paths:", d.get("memory_paths"))
print("  cwd:", d.get("cwd"))
print("  mcp_servers:", d.get("mcp_servers"))
PY
