#!/usr/bin/env bash
set -euo pipefail

probe=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
input=$(realpath "$1")
evidence=$(realpath -m "$2")
commit=$3
test "$(git -C "$input" rev-parse HEAD)" = "$commit"
pack="$input/examples/platform"
mkdir -p "$evidence/projection" "$evidence/learner"
build=$(mktemp -d)
trap 'rm -rf -- "$build"' EXIT

source_url=https://web.informatik.uni-mannheim.de/AnyBURL/AnyBURL-23-1x-sources.zip
source_sha=ef9857ffa918e93ac99884447e9ec1ddca987803af478f4c02d872136c35fd13
jdk=OpenJDK21U-jdk_x64_linux_hotspot_21.0.9_10.tar.gz
jdk_url=https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/$jdk
jdk_sha=810d3773df7e0d6c4394e4e244b264c8b30e0b05a0acf542d065fd78a6b65c2f

download() {
  local url=$1 file=$2 checksum=$3
  curl --fail --location --proto '=https' --proto-redir '=https' --retry 3 --silent --show-error "$url" -o "$file"
  echo "$checksum  $file" | sha256sum --check
}

cd "$build"
download "$source_url" anyburl-source.zip "$source_sha"
download "$jdk_url" "$jdk" "$jdk_sha"
mkdir jdk classes
unzip -q anyburl-source.zip
tar -xzf "$jdk" --strip-components=1 -C jdk
(
  cd src
  "$build/jdk/bin/javac" -encoding UTF-8 -d "$build/classes" de/unima/ki/anyburl/*.java
)
"$build/jdk/bin/jar" --create --date=2026-01-01T00:00:00Z --file AnyBURL.jar -C classes .
{
  printf 'publication_commit=%s\nanyburl_source_url=%s\nanyburl_source_sha256=%s\njdk_url=%s\njdk_sha256=%s\n' \
    "$commit" "$source_url" "$source_sha" "$jdk_url" "$jdk_sha"
  printf 'anyburl_jar_sha256=%s\n' "$(sha256sum AnyBURL.jar | cut -d' ' -f1)"
  "$build/jdk/bin/java" -version
  souffle --version
  python -c 'import duckdb; print(f"DuckDB {duckdb.__version__}")'
} > "$evidence/toolchain.txt" 2>&1

python "$probe/project.py" "$pack" "$evidence/projection" "$commit" 2> "$evidence/publication.log"
cp "$evidence/projection/facts.tsv" "$evidence/learner/facts.tsv"
cd "$evidence/learner"
{
  printf 'PATH_TRAINING = facts.tsv\nPATH_OUTPUT = rules\n'
  # The pinned learner snapshots when elapsed whole seconds are strictly greater than this setting.
  printf 'SNAPSHOTS_AT = 59\nWORKER_THREADS = 1\nBATCH_TIME = 1000\nZERO_RULES_ACTIVE = false\n'
  printf 'SINGLE_RELATIONS = %s\n' "$(cat "$evidence/projection/targets.txt")"
} > learn.properties
status=0
/usr/bin/time -f 'wall_seconds=%e\npeak_rss_kib=%M' -o timing.txt \
  timeout --kill-after=5s 75s "$build/jdk/bin/java" -Xms32m -Xmx512m -cp "$build/AnyBURL.jar" \
  de.unima.ki.anyburl.Learn learn.properties > stdout.log 2>&1 || status=$?
# The pinned upstream implementation uses exit code 1 after it finishes writing the last snapshot.
test "$status" = 1
grep -Eq 'CREATING SNAPSHOT 0 after 60 seconds' stdout.log
grep -Eq 'stored [0-9]+ rules in' stdout.log
test -s rules-59

python "$probe/replay.py" "$pack" "$evidence/projection" rules-59 "$evidence/report.json" \
  2> "$evidence/check.log"
python "$probe/replay.py" "$pack" "$evidence/projection" rules-59 "$evidence/replay.json" \
  2> "$evidence/replay.log"
cmp "$evidence/report.json" "$evidence/replay.json"
printf 'Replayed the retained raw snapshot with exactly matching comparison results.\n' > "$evidence/replay.txt"
