#!/bin/sh
# The CPUs a job can count on, for sizing a test runner's worker pool (docs/ci.md, section 5). Test runners size
# their pools from os.availableParallelism(): the CPUs of the node, not those of the job. On a shared Kubernetes
# pool a runner pod sees all 64 CPUs of a busy node but is guaranteed well under one, so Vitest started a worker
# per test file and tests timed out at random. The count, rounded up and at least 1:
#   1. the cgroup's CPU limit (cpu.max, or cpu.cfs_quota_us on cgroup v1), when there is one;
#   2. else, in a Kubernetes pod, its CPU request: what it gets when the node is busy, which the kubelet writes as
#      cpu.weight (cgroup v2) or cpu.shares (v1, 1024 per CPU);
#   3. else the CPUs it may run on (nproc).
# REZONO_CPUS overrides all three: a workstation that other work shares (scripts/preflight.sh sets it); CI never does.
# Never more than nproc. Plain POSIX sh: the same on GitHub's runners, ARC pods, Forgejo runners and a laptop.
#
#   scripts/cpus.sh           print the count
#   scripts/cpus.sh --report  also print what it is based on, and the cgroup's CPU pressure, to stderr
set -eu

n=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
cg=/sys/fs/cgroup
basis=nproc
cpus=$n

# 1. The limit: "<quota> <period>" in microseconds, or "max" (v2); a quota of -1 (v1).
quota=max period=100000
if [ -r $cg/cpu.max ]; then
	read -r quota period < $cg/cpu.max
elif [ -r $cg/cpu/cpu.cfs_quota_us ]; then
	quota=$(cat $cg/cpu/cpu.cfs_quota_us) period=$(cat $cg/cpu/cpu.cfs_period_us)
	if [ "$quota" -le 0 ]; then quota=max; fi
fi

# 2. The request, as CPU shares (1024 per CPU). The kubelet maps shares to weight as 1 + (shares - 2) * 9999 /
# 262142; this is its inverse. Outside Kubernetes a weight is a default, not a request, so it is not read.
shares=
if [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
	if [ -r $cg/cpu.weight ]; then
		shares=$(( 2 + ($(cat $cg/cpu.weight) - 1) * 262142 / 9999 ))
	elif [ -r $cg/cpu/cpu.shares ]; then
		shares=$(cat $cg/cpu/cpu.shares)
	fi
fi

if [ "$quota" != max ]; then
	basis=limit cpus=$(( (quota + period - 1) / period ))
elif [ -n "$shares" ]; then
	basis=request cpus=$(( (shares + 1023) / 1024 ))
fi
if [ -n "${REZONO_CPUS:-}" ]; then
	basis=REZONO_CPUS cpus=$REZONO_CPUS
fi
if [ "$cpus" -gt "$n" ]; then cpus=$n; fi
if [ "$cpus" -lt 1 ]; then cpus=1; fi

if [ "${1:-}" = --report ]; then
	{
		echo "cpus: $cpus by $basis (nproc=$n cpu.max=$quota/$period shares=${shares:--})"
		if command -v node > /dev/null; then node -e 'const p = require("os").availableParallelism();
			console.log(`cpus: os.availableParallelism()=${p}, so Vitest and node --test default to ${Math.max(p - 1, 1)} workers`)'; fi
		echo "cpus: loadavg $(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo -)"
		for f in cpu.stat cpu.pressure; do
			if [ -r $cg/$f ]; then grep -E '^(nr_throttled|throttled_usec|some)' $cg/$f | sed "s|^|cpus: $f |"; fi
		done
	} >&2
fi
echo "$cpus"
