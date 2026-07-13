#!/usr/bin/env python3
"""Runs a customer-supplied Playwright script inside a browser session.

Baked onto the CloudWorker worker AMI at /opt/cloudworker/run_playwright.py by
infra/packer/worker-ami.pkr.hcl. Not imported/run anywhere else — this only ever runs
on a worker instance, dispatched by
backend/app/infrastructure/aws/playwright_job_executor.py.

Records video for the whole session automatically and gives the script `page`,
`browser`, `context`, and `output_dir` to work with (e.g. call
page.screenshot(path=output_dir / "name.png") for an explicit screenshot). Everything
left in output_dir when the script finishes (video + any screenshots) is uploaded to
the artifacts bucket under jobs/{job_id}/artifacts/ using the instance's own IAM role.
"""

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: run_playwright.py <script_path> <job_id> <artifacts_bucket>",
            file=sys.stderr,
        )
        return 2

    script_path, job_id, artifacts_bucket = sys.argv[1], sys.argv[2], sys.argv[3]
    script_source = Path(script_path).read_text()

    output_dir = Path(tempfile.mkdtemp(prefix=f"cloudworker-{job_id}-"))
    exit_code = 0

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(record_video_dir=str(output_dir))
            page = context.new_page()

            namespace = {
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
                "output_dir": output_dir,
            }
            try:
                exec(compile(script_source, script_path, "exec"), namespace)
            except Exception:
                traceback.print_exc()
                exit_code = 1
            finally:
                context.close()
                browser.close()
    except Exception:
        traceback.print_exc()
        exit_code = 1

    _upload_artifacts(output_dir, artifacts_bucket, job_id)
    shutil.rmtree(output_dir, ignore_errors=True)
    return exit_code


def _upload_artifacts(output_dir: Path, bucket: str, job_id: str) -> None:
    s3 = boto3.client("s3")
    for file_path in output_dir.rglob("*"):
        if not file_path.is_file():
            continue
        key = f"jobs/{job_id}/artifacts/{file_path.name}"
        try:
            s3.upload_file(str(file_path), bucket, key)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    sys.exit(main())
