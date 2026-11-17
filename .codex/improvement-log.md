# Improvement Log - ai-document-analyzer

Use this file for evidence-backed harness improvements in this repo.

Keep entries short. Record real friction, recurring overhead, or meaningful improvements only.

## Promotion Thresholds

- 2 recurrences in this repo -> local `.codex/AGENTS.md` candidate
- 3 recurrences or safety-critical repetition -> script or skill candidate
- Cross-repo or clearly universal pattern -> global `~/.codex/AGENTS.md` candidate

## Entry Template

| Date | Task or Incident | Friction Observed | Evidence | Action Taken or Proposed | Promotion Target | Status |
| --- | --- | --- | --- | --- | --- | --- |
| YYYY-MM-DD |  |  |  |  | local AGENTS / script / skill / global AGENTS / none | captured |
| 2026-07-03 | Terraform ownership migration | The legacy package depended on a colocated `.oci` directory, creating a credential-publication hazard. | Terraform file provisioners reference `.oci`, while the source directory contained local credential files. | Added an explicit ignore rule and contract test; Deploy Studio alone injects credentials into its temporary archive. | local AGENTS | resolved |
| 2026-07-03 | Sentrux postflight | The historical redundancy threshold did not include a repository-owned declarative Terraform package. | Check measured 0.7379 while the structural gate reported no new cycles, coupling, or god files. | Documented a narrow 0.737 floor; keep the saved gate as the regression guard. | local rules | resolved |
