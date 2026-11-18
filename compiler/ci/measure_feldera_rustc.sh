#!/bin/sh
set -eu

rustc=$1
shift
crate=
incremental=false
debug=default
units=default
opt=default
previous=
for argument do
    if [ "$previous" = --crate-name ]; then
        crate=$argument
    fi
    option=
    if [ "$previous" = -C ]; then
        option=$argument
    else
        case "$argument" in -C*) option=${argument#-C} ;; esac
    fi
    case "$option" in
        incremental=*) incremental=true ;;
        debuginfo=*) debug=${option#debuginfo=} ;;
        codegen-units=*) units=${option#codegen-units=} ;;
        opt-level=*) opt=${option#opt-level=} ;;
    esac
    previous=$argument
done
set -- "$rustc" "$@"
if IFS= read -r original < /tmp/rezono-feldera-original-wrapper && [ -n "$original" ]; then
    set -- "$original" "$@"
fi
case "$crate" in
    ''|*[!a-zA-Z0-9_]*) exec "$@" ;;
esac
case "$debug" in default|none|line-directives-only|line-tables-only|limited|full|0|1|2) ;; *) debug=other ;; esac
case "$units" in default) ;; *[!0-9]*) units=other ;; esac
case "$opt" in default|0|1|2|3|s|z) ;; *) opt=other ;; esac

workspace=$(pwd -P) || exec "$@"
while [ "${workspace##*/}" != rust-compilation ]; do
    case "$workspace" in ''|/) exec "$@" ;; esac
    workspace=${workspace%/*}
done
log="$workspace/.rezono-rustc.log"
started=$(date +%s) || exec "$@"
# A diagnostic failure must leave rustc's original invocation and result intact.
if ! { printf 'rustc start crate=%s epoch=%s incremental=%s debuginfo=%s units=%s opt=%s\n' \
    "$crate" "$started" "$incremental" "$debug" "$units" "$opt" >> "$log"; } 2>/dev/null; then
    exec "$@"
fi
result=0
"$@" || result=$?
finished=$(date +%s) || exit "$result"
{ printf 'rustc finish crate=%s epoch=%s elapsed_seconds=%s status=%s\n' \
    "$crate" "$finished" "$((finished - started))" "$result" >> "$log"; } 2>/dev/null || true
exit "$result"
