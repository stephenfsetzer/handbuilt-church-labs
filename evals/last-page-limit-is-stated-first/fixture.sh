#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../_support/riverbend.sh"
sed -i.bak 's/closing_hymn_position: after_dismissal/closing_hymn_position: before_dismissal/' riverbend/worship/profile.yaml && rm riverbend/worship/profile.yaml.bak
