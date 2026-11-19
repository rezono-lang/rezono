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
case "$crate" in
    feldera_pipe_operator_????????????????)
        hash=${crate#feldera_pipe_operator_}
        case "$hash" in *[!a-f0-9]*) hash=;; esac
        if [ -n "$hash" ] && [ "$units" = 256 ] &&
           IFS= read -r operator_units 2>/dev/null < /tmp/rezono-oracle-input/operator-codegen-units &&
           [ "$operator_units" = 1 ]; then
            # Change only the observed flag; preserve argument order and boundaries.
            remaining=$#
            previous=
            while [ "$remaining" -gt 0 ]; do
                argument=$1
                shift
                if [ "$previous" = -C ] && [ "$argument" = codegen-units=256 ]; then
                    set -- "$@" "codegen-units=$operator_units"
                elif [ "$argument" = -Ccodegen-units=256 ]; then
                    set -- "$@" "-Ccodegen-units=$operator_units"
                else
                    set -- "$@" "$argument"
                fi
                previous=$argument
                remaining=$((remaining - 1))
            done
            units=$operator_units
        fi
        ;;
esac
set -- "$rustc" "$@"
if IFS= read -r original 2>/dev/null < /tmp/rezono-feldera-original-wrapper && [ -n "$original" ]; then
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
