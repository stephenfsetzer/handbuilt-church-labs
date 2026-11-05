#!/usr/bin/env bash
# Seed the run's workspace with the invented Riverbend church folder.
# Usage from a case's fixture.sh: source this file, then adjust files for the case.
set -euo pipefail
SUPPORT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SUPPORT_DIR/../.." && pwd)"
mkdir -p riverbend
cp -R "$PLUGIN_ROOT/scaffold/church-folder/." riverbend/
cat > riverbend/church.yaml <<'YAML'
church:
  name: Riverbend Episcopal Church
  short_name: Riverbend
  tradition: Episcopal
  city: Riverbend
  address: 10 Mill Lane
  website: riverbend.invalid
  regular_services:
    - day: Sunday
      time: "10:00"
lectionary:
  system: RCL
  track: Track 2
  translation: New Revised Standard Version Updated Edition
  optional_verses: appointed
  authorities:
    - name: The Lectionary Page
      url: https://lectionarypage.net/
sermon:
  selection_mode: lectionary
  primary_text: gospel
people:
  pastor: The Rev. Jordan Ellis
  celebrant: The Rev. Jordan Ellis
setup:
  schema_version: 3
  onboarded_on: "2026-08-26"
  plugin: handbuilt-church-labs
YAML
