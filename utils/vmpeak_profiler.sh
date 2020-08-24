#!/usr/bin/env bash

usage() {
cat <<EOF

Usage: $0 <executeable> [ARG...]

Run the given executable and log which child processes have what maximum memory
(VmPeak) usage.

Checks are performed once per second this can be adjusted by specifying
VMPEAK_INTERVAL.

The output file can be specified via VMPEAK_OUTFILE. The default is
"vmpeak.log".

After execution, the output file will contain one line for each child process:
<process-id>\t<VmPeak>\t<cmdline>

You can just prefix your waf build like so:
$ $0 waf configure build install <...>
and then identify which build steps take the most memory.

EOF
}

if (( $# == 0 )); then
    usage
    exit 0
fi

shopt -s extglob

args=( "${@}" )
stats_file="${VMPEAK_OUTFILE:-vmpeak.log}"
tmpfile="${stats_file}.tmp"
interval="${VMPEAK_INTERVAL:-1}"

echo -n "" >"${stats_file}"

"${args[@]}" &
exec_pid=$!

trap 'kill -9 ${exec_pid}' EXIT

# Usage: get_status <name> <pid>
get_status() {
    name="$1"
    pid="$2"
    echo -n "$(grep "^${name}:" "/proc/${pid}/status" | sed "s/^${name}:\s*//")"
}

# Usage: get_children <pid>
get_children() {
    pid="$1"
    local direct all
    direct="$(for f in /proc/"${pid}"/task/*/children; do [ -f "${f}" ] && cat "${f}"; done)"
    all="$(for cpid in ${direct}; do get_children "${cpid}"; echo -n " "; done)"
    all="${all% }"
    echo -n "${direct}${all:+ }${all}"
}

while kill -0 ${exec_pid} 2>/dev/null; do
    for child_pid in $(get_children "${exec_pid}" 2>/dev/null); do
        if [ ! -f "/proc/${child_pid}/cmdline" ] || [ ! -f "/proc/${child_pid}/status" ]; then
            continue
        fi
        echo -ne "${child_pid}\t" > "${tmpfile}"
        get_status VmPeak "${child_pid}" >> "${tmpfile}" || continue
        echo -ne "\t" >> "${tmpfile}"
        cmdline="/proc/${child_pid}/cmdline"
        if (( $(cat "${cmdline}" | wc -c) > 0 )); then
            cat "${cmdline}" | tr "\0\n" ' ' >> "${tmpfile}" || continue
        else
            get_status Name "${child_pid}" >> "${tmpfile}" || continue
        fi
        echo "" >> "${tmpfile}"
        cat >>"${stats_file}" <"${tmpfile}"
    done
    # sort by size in reverse and then uniquely for process id -> largest VmPeak
    sort -n -k 2 -r "${stats_file}" | sort -n -k 1 -u >"${stats_file}.uniq"
    mv "${stats_file}.uniq" "${stats_file}"
    sleep "${interval}"
done

trap - EXIT

# Final sort by peak memory usage
sort -n -k 2 "${stats_file}" > "${tmpfile}"
mv "${tmpfile}" "${stats_file}"
cat "${stats_file}"
