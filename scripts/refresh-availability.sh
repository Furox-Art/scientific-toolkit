#!/bin/bash
# Regenerate the committed availability report with the fully installed
# local environment (six upstream CLIs in .venv, axiomize-reason isolated).
cd /home/urkan/github/scientific-toolkit
export PATH="/home/urkan/github/scientific-toolkit/.venv/bin:$PATH"
export SCITOOL_REASON_BIN=/home/urkan/github/scientific-toolkit/.reason-pkg/bin/axiomize-reason
export PYTHONPATH=/home/urkan/github/scientific-toolkit/.reason-pkg
.venv/bin/python scripts/availability_report.py
