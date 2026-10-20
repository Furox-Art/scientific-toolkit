#!/bin/bash
# Regenerate the committed availability report with the fully installed
# local environment (seven upstream CLIs in .venv, the nomosguard module, and
# axiomize-reason isolated).
cd /home/urkan/github/scientific-toolkit
export PATH="/home/urkan/github/scientific-toolkit/.venv/bin:$PATH"
# SCITOOL_REASON_BIN points at the isolated console script only. No global
# PYTHONPATH is exported: an isolated install directory on PYTHONPATH shadows
# the standalone axiomize distribution, so availability_report.py scopes that
# directory to the single version probe that needs it.
export SCITOOL_REASON_BIN=/home/urkan/github/scientific-toolkit/.reason-pkg/bin/axiomize-reason
.venv/bin/python scripts/availability_report.py
