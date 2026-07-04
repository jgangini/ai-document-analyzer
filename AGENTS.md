# AI Document Analyzer Repository Instructions

- The Deploy Studio contract is `deploy-studio.json`; its Terraform package is `infra/terraform`.
- Never commit `infra/terraform/.oci`, OCI credentials, wallets, Terraform state, or generated runtime data.
- Keep infrastructure names derived from `deployment_suffix`; legacy name variables are compatibility overrides only.
- Before non-trivial changes run `./scripts/arch-preflight.ps1`; before completion run `./scripts/arch-postflight.ps1`.
- Validate contract changes with `python -m unittest tests.test_deploy_studio_contract` and Terraform with `fmt -check`, `init -backend=false`, and `validate`.
