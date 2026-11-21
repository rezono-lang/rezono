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
offline, use the locked Python and Soufflé environment from the workflow. The detached checkout
must preserve the Git bytes of the pinned fact files.

```sh
git -c core.autocrlf=false -c core.eol=lf worktree add --detach pinned a1bc4a2612ae74eb6556c90e7f8efab309d93cdc
# Download artifact 14476974527 from run 44405578238 and verify its SHA-256:
# 10dbf9621cafc4e666b0a45b5baf6b37ba3abb7c8b300b1da88b9b08b4e33aa0  44405578238.zip
unzip -q 44405578238.zip -d evidence
python probes/anyburl/replay.py pinned/examples/platform evidence/projection \
  evidence/learner/rules-59 replay.json
cmp evidence/report.json replay.json
```

## Recorded run

Run `44405578238` succeeded on its first attempt at workflow commit
`15d0e4a80e01503c41f401fba39be384e22ee9dd`. Its checker publication `m-1` supplied
1,074 unique, reversible triples from 407 verified kind and slot snapshots. The learner
sampled 129 nonempty closed head predicates and retained all 1,543 raw rules. The learner
logged its snapshot at 60 learning seconds. GNU time measured 61.68 seconds elapsed and
468,200 KiB peak RSS for the Java process with startup and snapshot writing. The complete
workflow job took 40 minutes and 37 seconds, including both compiler replays.
[Hosted run](https://github.com/rezono-lang/rezono/actions/runs/44405578238)

All 575 raw rules with confidence at least 0.9 appear in raw-line order in the report.
The remaining 968 rules are preserved in the raw snapshot. The two complete replay
reports were byte-identical.

| Outcome | Candidates | Reason |
| --- | ---: | --- |
| Unexpressible | 111 | A variable kind cannot name one relation in the ordinary rule language. |
| Provenance gap | 245 | At least one original remainder row lacked a verified source and reason. |
| Candidate too large | 217 | The rule and charged support facts failed the strict canonical byte bound. |
| Excess rows | 2 | The rule inferred rows outside the pinned original set. |
| Eligible | 0 | |

No inexact candidate met the 5% exception threshold. The closest was raw line 1203.
It missed `cluster_service_binding("cp")`, one of 19 original rows (5.26%), and
inferred no excess. Raw line 620 added two `owner` values for
`cluster_owned_endpoint__network` and missed 13 original rows. Raw line 1011 added
two `zone__isolated_recovery` rows and missed two. The archive lists every exact
counterexample and provenance gap.

The binary evidence archive (`44405578238.zip`, SHA-256
`10dbf9621cafc4e666b0a45b5baf6b37ba3abb7c8b300b1da88b9b08b4e33aa0`) is no longer stored in Git:
the probe produced 1,543 raw rules and 0 eligible candidates, recorded in the
[import proposal decision](../../decisions/anyburl-import-proposals.md). That archive holds the
unmodified raw rules, per-candidate report, exact projection and snapshot pins, settings,
toolchain measurements, and one copy of the matching report. The hosted artifact has ID
`14476974527` and GitHub digest
`872a2a3e79af557e6ab5da82de06408db8fc9132cb1fde0555b7b1fc55cbe658`.
[Hosted artifact](https://github.com/rezono-lang/rezono/actions/runs/44405578238/artifacts/14476974527)

| Evidence | SHA-256 |
| --- | --- |
| Pack definition | `7a239958fef9817cde6530f552fa402a7f791e2e2ad00199d2ddf503081e21dd` |
| Canonical map of the 38 Git fact and source file digests | `64e8eece2f9a0094a502f5564d1e820f16eecfdb2aecaa312174d69f1a078587` |
| Projected triples | `75832d58bc2cc5887962dc8ebdb1c852f6a68cd07fab3bda38088e8d164e5c90` |
| Snapshot and input manifest | `1b1fb6672c4a6b377420f9d698c1cccd1bf02d20e0f68792ac1515bba75f0352` |
| Source-built AnyBURL JAR | `82ea2ff5b36b9d9f85652de8ddba7b1d5c5f5b7bcee8847620de5d5575635d2f` |
| Learner settings | `7fc962319a1107ceec351143c10ecde7ac48653bf24ef9e37926127f40f0b57c` |
| Raw rules | `fa8d0dfda9976db175bf19a8d9439d5f187a317ef59ef3d8afbe9efa2fa1dc78` |
| Both replay reports | `b0650571fbb825bdc9eba84eb47bd61888e83c0c6b18e3f011675294223b9b09` |
| Durable evidence archive | `10dbf9621cafc4e666b0a45b5baf6b37ba3abb7c8b300b1da88b9b08b4e33aa0` |

## Preflight

The pinned platform publication produced 1,074 triples from 407 verified snapshots. The triple file's
SHA-256 is `75832d58bc2cc5887962dc8ebdb1c852f6a68cd07fab3bda38088e8d164e5c90`.
A one-second smoke run produced 34 raw rules, with a maximum confidence of 0.875. Replaying that
snapshot gave byte-identical reports. A separately authored candidate exercised the compiler path
on the same publication. DuckDB and Soufflé agreed on one missing and one excess row.
