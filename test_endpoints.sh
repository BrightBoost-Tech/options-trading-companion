#!/bin/bash

BASE_URL="http://localhost:8000"

echo "Testing /optimize/portfolio (Classical)..."
curl -X POST "$BASE_URL/optimize/portfolio" \
    -H "Content-Type: application/json" \
    -d '{
        "user_id": "75ee12ad-b119-4f32-aeea-19b4ef55d587",
        "positions": [
            {"symbol": "AAPL", "current_value": 15000, "current_quantity": 100, "current_price": 150},
            {"symbol": "GOOG", "current_value": 20000, "current_quantity": 10, "current_price": 2000}
        ],
        "risk_aversion": 1.0,
        "skew_preference": 0.0,
        "cash_balance": 5000
    }'
echo -e "\n"

echo "Testing /optimize/portfolio (Quantum)..."
curl -X POST "$BASE_URL/optimize/portfolio" \
    -H "Content-Type: application/json" \
    -d '{
        "user_id": "75ee12ad-b119-4f32-aeea-19b4ef55d587",
        "positions": [
            {"symbol": "AAPL", "current_value": 15000, "current_quantity": 100, "current_price": 150},
            {"symbol": "GOOG", "current_value": 20000, "current_quantity": 10, "current_price": 2000}
        ],
        "risk_aversion": 1.0,
        "skew_preference": 10.0,
        "cash_balance": 5000
    }'
echo -e "\n"

echo -e "\n"
