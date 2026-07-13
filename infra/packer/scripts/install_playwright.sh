#!/usr/bin/env bash
set -euo pipefail

sudo dnf install -y python3 python3-pip

python3 -m pip install --upgrade pip
python3 -m pip install playwright==1.49.0 boto3==1.35.90

# Installs Chromium plus the OS-level libraries Playwright needs (fonts, libnss3, etc).
sudo python3 -m playwright install --with-deps chromium
