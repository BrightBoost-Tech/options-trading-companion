#!/bin/bash
echo "Testing /optimize/quantum-ready (Standard)..."
curl -v -X POST http://localhost:8000/optimize/quantum-ready \
  -H "Content-Type: application/json" \
  -d '{
    "tickers": ["AAPL", "GOOGL", "TSLA", "AMD"],
    "risk_aversion": 1.0,
    "skew_preference": 0.0,
    "max_position_pct": 1.0
  }'

echo -e "\n\nTesting /optimize/quantum-ready (Skew Aware)..."
curl -v -X POST http://localhost:8000/optimize/quantum-ready \
  -H "Content-Type: application/json" \
  -d '{
    "tickers": ["AAPL", "GOOGL", "TSLA", "AMD"],
    "risk_aversion": 1.0,
    "skew_preference": 10.0,
    "max_position_pct": 1.0
  }'

echo -e "\n\nTesting /scout/weekly..."
curl -v http://localhost:8000/scout/weekly

echo -e "\n\nTesting /journal/stats..."
curl -v http://localhost:8000/journal/stats
