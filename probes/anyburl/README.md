# AnyBURL platform probe

The [import rule proposal decision](../../decisions/import-rule-proposals.md) defines this experiment.
It uses the publication of `examples/platform` at
`a1bc4a2612ae74eb6556c90e7f8efab309d93cdc` and the rule proposal checker from the same commit.

## Inputs

The ordinary publisher writes the complete checker view. The probe verifies each published snapshot
digest and checks that the projected rows agree with the pinned pack facts. It writes one triple
for each kind or slot row. Kind membership uses `is`, and a slot uses its table name. The subject and
object encode the value and its kind or type as UTF-8 JSON in hexadecimal. Replaying decodes them
and verifies their domains. Open input facts can appear as positive premises. The learner samples
only nonempty closed predicates as heads, where an unobserved target can be counted as absent.

AnyBURL `23-1x` is built from the official source archive with SHA-256
`ef9857ffa918e93ac99884447e9ec1ddca987803af478f4c02d872136c35fd13`.
The project page states the BSD-3-Clause licence. [AnyBURL release and licence](https://web.informatik.uni-mannheim.de/AnyBURL/#license)

The build uses Temurin JDK `21.0.9+10` for Linux x64, with SHA-256
`810d3773df7e0d6c4394e4e244b264c8b30e0b05a0acf542d065fd78a6b65c2f`.
The probe checks both archive digests before extraction. [Temurin release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.9%2B10)

## Run and replay

Run **AnyBURL platform probe** manually in GitHub Actions. The learner uses one worker and records
a snapshot at 60 elapsed learning seconds. Upstream takes the snapshot on the first whole second
strictly after its setting, so the properties file contains `SNAPSHOTS_AT = 59`. The job verifies
the reported time and a completed rule write. The artifact records the measured process wall
time and peak RSS, which include JVM startup and snapshot writing.

The evidence artifact holds the exact triples and digests, toolchain and settings, raw rules,
the compiler result for every translatable candidate with confidence at least 0.9, and the
reason for each candidate outside the rule language. When a candidate misses or adds rows,
the report shows the exact differences. A total difference of at most 5% of the original set
marks possible exceptions for review. The ordinary compiler owns the final eligibility result.

The workflow evaluates the raw snapshot twice and compares the resulting JSON bytes. To replay
offline, use the same pinned checkout and locked Python and Soufflé environment. Give the replay
script the pinned source pack, the artifact's `projection` directory and its raw rule snapshot.

```sh
python probes/anyburl/replay.py pinned/examples/platform evidence/projection \
  evidence/learner/rules-59 replay.json
cmp evidence/report.json replay.json
```

## Preflight

The pinned platform publication produced 1,074 triples from 407 verified snapshots. The triple file's
SHA-256 is `75832d58bc2cc5887962dc8ebdb1c852f6a68cd07fab3bda38088e8d164e5c90`.
A one-second smoke run produced 34 raw rules, with a maximum confidence of 0.875. Replaying that
snapshot gave byte-identical reports. A separately authored candidate exercised the compiler path
on the same publication. DuckDB and Soufflé agreed on one missing and one excess row.
