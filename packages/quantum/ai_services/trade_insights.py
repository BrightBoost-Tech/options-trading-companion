# ai_services/trade_insights.py
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import json

# Pydantic model for structured output
class TradeInsight(BaseModel):
    pattern_detected: str
    risk_assessment: str
    success_probability: float = Field(ge=0.0, le=1.0)
    similar_strategies: List[str]
    recommendation: str
    confidence: float = Field(ge=0.0, le=1.0)

# The prompt template with chain-of-thought reasoning
TRADE_INSIGHT_PROMPT = """Analyze this options trade and provide insights.

Follow this analytical framework:
1. Identify what strategy pattern this trade represents
2. Assess the key risks for this specific trade
3. Estimate success probability based on the setup
4. Note similar strategies and their typical outcomes
5. Provide a specific, actionable recommendation

Trade data:
{trade_json}

Output your analysis as structured JSON matching this exact schema:
{{
  "pattern_detected": "Name of the strategy pattern (e.g., covered call, iron condor, etc.)",
  "risk_assessment": "Key risks to watch for this trade",
  "success_probability": 0.0 to 1.0,
  "similar_strategies": ["list", "of", "related", "strategies"],
  "recommendation": "Specific actionable advice",
  "confidence": 0.0 to 1.0
}}
"""

def analyze_trade(trade_data: dict) -> TradeInsight:
    """
    Analyze a single trade and return structured insights.
    
    Args:
        trade_data: Dictionary containing trade details
        
    Returns:
        TradeInsight object with AI-generated analysis
    """
    # Create Gemini client
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    # Format the prompt
    prompt = TRADE_INSIGHT_PROMPT.format(
        trade_json=json.dumps(trade_data, indent=2)
    )
    
    # Call Gemini with structured output
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3  # Lower temperature for factual analysis
        )
    )
    
    # Parse and validate response
    insight = TradeInsight.model_validate_json(response.text)
    
    return insight


# Test function
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    # Example trade
    test_trade = {
        "symbol": "AAPL",
        "type": "option",
        "direction": "sell",
        "contract_type": "call",
        "strike": 185,
        "expiration": "2025-12-20",
        "premium": 3.50,
        "quantity": 1,
        "underlying_price": 180,
        "notes": "Selling covered call against 100 shares"
    }
    
    print("Analyzing trade...")
    insight = analyze_trade(test_trade)
    
    print("\n✅ Trade Analysis Complete!")
    print(f"Pattern: {insight.pattern_detected}")
    print(f"Risk: {insight.risk_assessment}")
    print(f"Success Probability: {insight.success_probability:.0%}")
    print(f"Recommendation: {insight.recommendation}")
    print(f"Confidence: {insight.confidence:.0%}")
