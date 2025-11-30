#!/bin/bash
# Test Phase 2 Diagnostics
echo "Testing Phase 1 Diagnostics..."
curl -s http://127.0.0.1:8000/optimize/diagnostics/phase1 | python3 -m json.tool

echo "Testing Phase 2 QCI Uplink (Expect Skipped or Error if no token)..."
curl -X POST http://127.0.0.1:8000/optimize/diagnostics/phase2/qci_uplink | python3 -m json.tool
