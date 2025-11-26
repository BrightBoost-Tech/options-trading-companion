#!/bin/bash

BASE_URL="http://localhost:8000"

echo "Testing /optimize/portfolio..."
curl -X POST "$BASE_URL/optimize/portfolio" \
    -H "Content-Type: application/json" \
    -d '{
        "user_id": "75ee12ad-b119-4f32-aeea-19b4ef55d587",
        "current_positions": [
            {"symbol": "AAPL", "quantity": 100, "current_price": 150, "market_value": 15000, "pnl_pct": 10},
            {"symbol": "GOOG", "quantity": 10, "current_price": 2000, "market_value": 20000, "pnl_pct": -60}
        ],
        "risk_tolerance": 0.5,
        "cash_balance": 5000
    }'
echo -e "\n"

echo "Testing /scout/weekly..."
curl -X GET "$BASE_URL/scout/weekly?risk_tolerance=0.5"
echo -e "\n"
