#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../_support/riverbend.sh"
sed -i.bak '/translation:/d' riverbend/church.yaml && rm riverbend/church.yaml.bak
