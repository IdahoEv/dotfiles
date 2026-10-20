#!/usr/bin/env bash
# prompt-metrics.sh — size breakdown of a prompt file, for the bloat check.
#
#   prompt-metrics.sh <file> [<file> ...]
#
# Prints key=value on stdout, one line per file then one per "## " section:
#
#   file=<path> lines=<n> words=<n> sections=<n>
#   section=<title> file=<path> lines=<n> words=<n>
#
# Words count prose only: fenced code blocks are excluded and markdown
# punctuation is stripped. A section far out of proportion to what it
# instructs is the signal — compare sections against each other, not
# against an absolute budget.
#
# Read-only. Exits 1 on an unreadable file.

set -euo pipefail

[ $# -ge 1 ] || { echo "usage: prompt-metrics.sh <file> [<file> ...]" >&2; exit 1; }

for f in "$@"; do
  [ -r "$f" ] || { echo "cannot read: $f" >&2; exit 1; }

  awk -v path="$f" '
    function words(s,   n, i, parts, c) {
      gsub(/[^a-zA-Z0-9 ]/, " ", s)
      n = split(s, parts, " ")
      c = 0
      for (i = 1; i <= n; i++) if (parts[i] != "") c++
      return c
    }

    function flush() {
      if (title != "")
        out[++nout] = sprintf("section=%s file=%s lines=%d words=%d", title, path, slines, swords)
    }

    /^```/ { fence = !fence; next }
    fence  { next }

    /^## / {
      flush()
      nsec++
      title = substr($0, 4)
      gsub(/[^a-zA-Z0-9]+/, "-", title)
      slines = 0
      swords = 0
      next
    }

    {
      w = words($0)
      tlines++
      twords += w
      if (title != "") { slines++; swords += w }
    }

    END {
      flush()
      printf "file=%s lines=%d words=%d sections=%d\n", path, tlines, twords, nsec
      for (i = 1; i <= nout; i++) print out[i]
    }
  ' "$f"
done
