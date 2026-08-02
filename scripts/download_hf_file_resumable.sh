#!/bin/zsh

set -u

if [[ $# -ne 3 ]]; then
  print -u2 "usage: $0 URL OUTPUT EXPECTED_BYTES"
  exit 2
fi

url=$1
output=$2
expected_bytes=$3

mkdir -p "${output:h}"

while true; do
  if [[ -f "$output" ]]; then
    current_bytes=$(stat -f %z "$output")
  else
    current_bytes=0
  fi

  if (( current_bytes == expected_bytes )); then
    print "complete: $output ($current_bytes bytes)"
    exit 0
  fi

  if (( current_bytes > expected_bytes )); then
    print -u2 "output is larger than expected: $current_bytes > $expected_bytes"
    exit 3
  fi

  print "resume: $output at $current_bytes / $expected_bytes bytes"
  curl \
    --fail \
    --location \
    --http1.1 \
    --connect-timeout 30 \
    --max-time 1800 \
    --retry 5 \
    --retry-all-errors \
    --retry-delay 2 \
    --continue-at - \
    --output "$output" \
    "$url"

  curl_status=$?
  current_bytes=$(stat -f %z "$output" 2>/dev/null || print 0)
  print "curl exit=$curl_status; retained=$current_bytes / $expected_bytes bytes"
  sleep 2
done
