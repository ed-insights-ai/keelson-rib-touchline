# Touchline

Touchline v1 collects the published 2026 college-soccer schedule and roster,
then renders those files as a living season board. Those two files are the
complete first deliverable; historical box scores, standings, Postgres,
parquet, and generated reports are outside the first-contact flow.

`/touchline <folder-name>` creates an ordinary data directory under Keelson's
default workspace and registers it for UI/workflow scope. It is not initialized
as a Git repository, and Git is not required.

Conference scope is configuration, not identity: the first deployment covers
the GAC, and schools/conferences are defined per data home.

The original product and implementation contract lives in the
[Touchline rib specification](https://github.com/ed-insights-ai/ed-insights-platform/blob/main/docs/specs/touchline-rib.md).
