# AI Document Analyzer Terraform Package

This Resource Manager package creates the OCI resources and fully configures the published AI Document Analyzer container.

Runtime model:

- CloudTechNext validates OCI credentials and creates the Resource Manager stack.
- Terraform provisions VCN, subnet, security list, Autonomous Database 26ai, Object Storage bucket and one Oracle Linux VM.
- The VM installs Docker, clones `https://github.com/jgangini/ai-document-analyzer`, builds the container locally and starts it on port 80 with persistent runtime directories.
- The installer materializes missing OCI SVG assets before `docker build` if the published repository cut does not contain them yet.
- CloudTechNext automation injects the generated wallet, OCI API key, Object Storage bucket, Generative AI settings and SQL bootstrap through the application's setup API during Resource Manager apply.
