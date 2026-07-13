# Worker AMI (Packer)

Builds a CloudWorker worker AMI: the same Amazon Linux 2023 base Phase 3's Terraform launch
template already references, with Playwright + Chromium and the `run_playwright.py` runner harness
baked in at `/opt/cloudworker/run_playwright.py`. One AMI serves both `shell` and `browser` jobs —
shell jobs simply don't touch the Playwright bits.

**This has not been built in development** — building an AMI requires launching a real EC2
instance (Packer's `amazon-ebs` builder), which needs real AWS credentials this environment
doesn't have, the same reason `infra/terraform`'s `apply` hasn't been run either. The template is
authored and (where possible) syntax-checked, not built.

## Build it (once you have real AWS credentials)

```bash
cd infra/packer
packer init .
packer validate .
packer build worker-ami.pkr.hcl
```

Note the resulting AMI id from the build output, then set it as
`infra/terraform/environments/dev`'s `custom_ami_id` variable (or `TF_VAR_custom_ami_id`) and
re-apply — the compute module falls back to the stock AL2023 SSM-parameter AMI when this isn't
set, so shell-only deployments aren't forced to build this first.

## Rebuilding

There's no automatic rebuild pipeline yet (tracked as tech debt) — bump `playwright`/`boto3`
versions in `scripts/install_playwright.sh`, re-run the build, and update `custom_ami_id` when you
want a newer image. Old AMIs aren't automatically cleaned up.
