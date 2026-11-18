# Which releases approach the end of support?

Accept an ISO calendar date and a nonnegative whole number of days. For each running release, return service, release, vendor support end date, source URL and SHA-256 of the source bytes when the end date falls in the closed interval from that date through that date plus the supplied days. Sort by end date, service and release. Report missing vendor evidence separately as unknown. Use the upstream maintenance window applicable to the named release. A newer stable release alone says nothing about continued support.

A wall-clock query would change between runs. Explicit dates also make both endpoints testable. A support statement is an authored record keyed by release, support channel and evidence, since the release date cannot establish its end of support.
