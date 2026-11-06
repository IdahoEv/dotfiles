#!/usr/bin/env bash
set -uo pipefail

lib_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
manifest="$lib_dir/packages.tsv"
linux_script="$lib_dir/../bootstrap-linux.sh"
failures=0

check() { # check <description> <condition-exit-status>
  if [[ "$2" == 0 ]]; then printf 'PASS %s\n' "$1"; else printf 'FAIL %s\n' "$1" >&2; failures=$((failures + 1)); fi
}

rows() { grep -v -e '^#' -e '^[[:space:]]*$' "$manifest"; }

check "every row has exactly four non-empty tab-separated columns" \
  "$(rows | awk -F'\t' 'NF != 4 || $1 == "" || $2 == "" || $3 == "" || $4 == "" {bad = 1} END {print bad + 0}')"

check "tiers are core, dev, search, or cask" \
  "$(rows | awk -F'\t' '$1 !~ /^(core|dev|search|cask)$/ {bad = 1} END {print bad + 0}')"

check "names are unique" \
  "$(rows | cut -f2 | sort | uniq -d | wc -l | tr -d ' ')"

check "casks have no apt equivalent" \
  "$(rows | awk -F'\t' '$1 == "cask" && $3 != "none" {bad = 1} END {print bad + 0}')"

check "brew column never names an installer" \
  "$(rows | awk -F'\t' '$4 ~ /^installer:/ {bad = 1} END {print bad + 0}')"

unknown=0
while IFS= read -r id; do
  grep -qF "installer:$id)" "$linux_script" || { printf 'no handler for installer:%s\n' "$id" >&2; unknown=1; }
done < <(rows | cut -f3 | sed -n 's/^installer://p')
check "every apt installer id has a handler in bootstrap-linux.sh" "$unknown"

exit $((failures > 0))
