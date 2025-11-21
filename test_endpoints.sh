#!/bin/bash
echo "Testing /compare/real..."
curl -v -X POST http://localhost:8000/compare/real \
  -H "Content-Type: application/json" \
  -d '{
    "symbols": ["SPY", "QQQ", "IWM", "DIA", "VTI"],
    "risk_aversion": 2.0
  }'

echo -e "\n\nTesting /scout/weekly..."
curl -v http://localhost:8000/scout/weekly

echo -e "\n\nTesting /journal/stats..."
curl -v http://localhost:8000/journal/stats
