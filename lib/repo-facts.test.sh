#!/usr/bin/env bash
# lib/repo-facts.test.sh — behavioral checks for the label helpers.
#
#   lib/repo-facts.test.sh
#
# This repo has no test framework and does not want one; this is a plain script
# that exits non-zero on the first failure, so it works as a pre-commit check
# and in any CI that can run bash.
#
# Run it with the SAME interpreter the tools use — `/usr/bin/env bash`, which on
# macOS is bash 3.2, not whatever 5.x is on PATH as `bash`. Several of the cases
# below only fail on 3.2 (the empty-array/`set -u` rule was relaxed in 4.4), so
# testing under 5.x alone silently passes bugs that abort the real scripts.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

pass=0 fail=0

check() {  # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL %s\n  expected: [%s]\n  actual:   [%s]\n' "$1" "$2" "$3" >&2
  fi
}

# Runs a snippet in a fresh `set -euo pipefail` bash, printing its output, or
# "ABORT:<rc>" if it died — which is how the errexit regressions announce
# themselves rather than just returning the wrong string.
in_strict_bash() {  # <snippet> → output, or ABORT:<rc>
  local out rc
  out="$(/usr/bin/env bash -c "set -euo pipefail
. ./lib/repo-facts.sh
$1" 2>/dev/null)" && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then printf 'ABORT:%s' "$rc"; else printf '%s' "$out"; fi
}

# ---- gt::distill_title ------------------------------------------------------
. ./lib/repo-facts.sh

check "strips leading tags, parens, stopwords, verb; keeps tail" \
  "Data Deletion Retention Policy" \
  "$(GT_LABEL_NOISE="pers" gt::distill_title \
     '[A/L] Decide PERS data deletion & retention policy (member deletion)')"

check "strips multiple leading tags" \
  "Collector Adapter Contract" \
  "$(gt::distill_title '[A] [ops] Build the collector adapter contract')"

# Only LEADING tags are stripped; an inline one is just punctuation, so its
# contents go through the normal stopword/verb rules ("a" is a stopword, "Fix"
# a leading verb) rather than being removed as a tag.
check "an inline bracketed tag is not treated as a track tag" \
  "Thing" \
  "$(gt::distill_title 'Fix [a] thing' 9)"

check "preserves acronym case" \
  "Trace APM Log Correlation" \
  "$(gt::distill_title 'Enable dd-trace APM log correlation')"

check "empty title yields empty, not an error" "" "$(gt::distill_title '')"
check "title of only tags yields empty"        "" "$(gt::distill_title '[A/L]')"
check "title of only stopwords yields empty"   "" "$(gt::distill_title 'the and of')"

# A glob in the title must not expand against the cwd. Guarded by `tr`, but the
# word-split that consumes it is deliberately unquoted, so this stays pinned.
check "glob in title does not expand" \
  "Bug" \
  "$(gt::distill_title 'Fix the * bug')"

# Regression: maxw <= 0 leaves the output array empty, which under bash 3.2 +
# `set -u` is an unbound-variable error that aborts the CALLER, not just a bad
# label. Reachable via GT_LABEL_WORDS=0 or an explicit 0 argument.
# maxw is clamped to >= 1, so these return the last word rather than aborting.
# The assertion that matters is "not ABORT:<rc>".
check "maxw=0 does not abort a strict caller" \
  "Thing" \
  "$(in_strict_bash 'gt::distill_title "Build the rewards thing" 0')"

check "GT_LABEL_WORDS=0 does not abort a strict caller" \
  "Thing" \
  "$(in_strict_bash 'GT_LABEL_WORDS=0 gt::distill_title "Build the rewards thing"')"

check "negative maxw does not abort a strict caller" \
  "Thing" \
  "$(in_strict_bash 'gt::distill_title "Build the rewards thing" -3')"

# ---- gt::sanitize_label / override ------------------------------------------
check "override wins over the title" \
  "Planner Drops Subjects" \
  "$(GT_LABEL_OVERRIDE='Planner Drops Subjects' gt::label_from_title 'Investigate why the planner drops subjects')"

check "unusable override falls back to the distiller" \
  "Rewards Thing" \
  "$(GT_LABEL_OVERRIDE='!!!' gt::label_from_title 'Build the rewards thing' 2)"

check "empty override falls back to the distiller" \
  "Rewards Thing" \
  "$(GT_LABEL_OVERRIDE='' gt::label_from_title 'Build the rewards thing' 2)"

check "path traversal is flattened" \
  "etc passwd" \
  "$(gt::sanitize_label '../../etc/passwd')"

check "shell metacharacters are flattened" \
  "feat evil rm rf" \
  "$(gt::sanitize_label 'feat/evil; rm -rf ~')"

check "leading dashes and slashes cannot survive" \
  "rf force tmp" \
  "$(gt::sanitize_label '   -rf --force /tmp   ')"

check "a single overlong word is rejected (caller falls back)" \
  "" \
  "$(gt::sanitize_label 'Supercalifragilisticexpialidociousandthensomemoreandmore')"

# Regression: a non-default IFS broke both the split (`set -- $s`) and the
# re-join (`s="$*"`), leaving leading/trailing spaces that became leading
# hyphens in a branch name, and joining words with IFS[0].
# Exercised via the SLUG override, since that is the path where a sanitized
# value reaches a git ref; GT_LABEL_OVERRIDE no longer affects the slug.
check "non-default IFS does not leak separators into a slug" \
  "rewards-structures" \
  "$(in_strict_bash 'IFS=,
GT_LABEL_SLUG_OVERRIDE="  Rewards/Structures  "
gt::slug_title "Design unified rewards representation"')"

check "non-default IFS does not leak separators into a label" \
  "Rewards Structures" \
  "$(in_strict_bash 'IFS=,
GT_LABEL_OVERRIDE="  Rewards/Structures  "
gt::label_from_title "Design unified rewards representation"')"

# Regression: a non-numeric cap made `[ -gt ]` exit 2, which the `if` read as
# false, skipping the length cap entirely and passing a 199-char override into
# a branch name.
# "<= 48", not "== 48": the trim drops whole words, so it lands on the last
# word boundary at or under the cap (44 for this input), never mid-word.
check "non-numeric GT_LABEL_MAX_CHARS still caps" \
  "capped" \
  "$(in_strict_bash 'export GT_LABEL_MAX_CHARS=48x
GT_LABEL_OVERRIDE="$(printf "word %.0s" $(seq 1 40))"
r="$(gt::sanitize_label "$GT_LABEL_OVERRIDE")"
[ "${#r}" -le 48 ] && printf "capped" || printf "%s" "${#r}"')"

check "a sane GT_LABEL_MAX_CHARS is honored" \
  "capped" \
  "$(in_strict_bash 'export GT_LABEL_MAX_CHARS=20
GT_LABEL_OVERRIDE="$(printf "word %.0s" $(seq 1 40))"
r="$(gt::sanitize_label "$GT_LABEL_OVERRIDE")"
[ "${#r}" -le 20 ] && printf "capped" || printf "%s" "${#r}"')"

# ---- label/slug split -------------------------------------------------------
# The core invariant: $GT_LABEL_OVERRIDE moves the DISPLAY LABEL and must not
# move the branch slug, because a branch name is matched against later
# (find_ticket_branch, an open PR, shell history) while a label is not.
_split_title='Investigate why the planner drops subjects with no applicable_date'

check "override moves the display label" \
  "Planner Drops Subjects" \
  "$(GT_LABEL_OVERRIDE='Planner Drops Subjects' gt::label_from_title "$_split_title")"

check "override does NOT move the slug" \
  "$(gt::slug_title "$_split_title")" \
  "$(GT_LABEL_OVERRIDE='Planner Drops Subjects' gt::slug_title "$_split_title")"

check "slug override is the explicit escape hatch" \
  "planner-drops-subjects" \
  "$(GT_LABEL_SLUG_OVERRIDE='Planner Drops Subjects' gt::slug_title "$_split_title")"

check "an unusable slug override falls back to the distiller" \
  "$(gt::slug_title "$_split_title")" \
  "$(GT_LABEL_SLUG_OVERRIDE='!!!' gt::slug_title "$_split_title")"

# ---- locale stability -------------------------------------------------------
# Regression: `tr -c '[:alnum:]'` is locale-dependent. Under LC_ALL=C each byte
# of a multibyte char is a separator, so "Café" became "Caf" — the half-word
# defect this whole change exists to remove — while under UTF-8 non-ASCII
# letters passed through into a git ref. A cron caller has C, an interactive
# shell has UTF-8, so one ticket got two different names.
_utf8="$(LC_ALL=en_US.UTF-8 /usr/bin/env bash -c '. ./lib/repo-facts.sh; gt::slug_title "Café naïve dash parser"' 2>/dev/null)"
_c="$(LC_ALL=C          /usr/bin/env bash -c '. ./lib/repo-facts.sh; gt::slug_title "Café naïve dash parser"' 2>/dev/null)"
check "slug is identical under LC_ALL=C and UTF-8" "$_utf8" "$_c"
# Non-ASCII letters are STRIPPED, not transliterated: "Café" -> "caf".
# Transliteration would need iconv, and a missing/varying iconv would
# reintroduce exactly the cross-caller instability this pins down. Stripping is
# lossy but identical everywhere, which is the property that matters for a name
# used to find an existing branch.
check "non-ASCII is stripped, not passed into a slug" "caf-na-ve-dash-parser" "$_c"

# ---- report -----------------------------------------------------------------
printf 'repo-facts: %d passed, %d failed (bash %s)\n' "$pass" "$fail" "${BASH_VERSION%%(*}"
[ "$fail" -eq 0 ]
