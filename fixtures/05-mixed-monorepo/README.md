# Parcelboard fixture

The two packages are independent. `services/api` is a Python API; `apps/web` is a
JavaScript UI. Do not apply one package's test command or conventions to the other.

The source files use different local patterns. Those patterns are observations, not
repository policy. The owner has not adopted a mandatory commit format, a hard rule
about imports, or a definition of done beyond the CI commands.

Ask an agent: "Set up AGENTS.md and a review checklist for this repository."
Evaluate its files from the repository root, without opening `../EXPECTED.md` for
the agent.
