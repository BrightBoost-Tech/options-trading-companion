import os
from dotenv import load_dotenv

load_dotenv()

ENABLE_REBALANCE_CONVICTION = os.getenv("ENABLE_REBALANCE_CONVICTION", "false").lower() == "true"
ENABLE_REBALANCE_CONVICTION_SHADOW = os.getenv("ENABLE_REBALANCE_CONVICTION_SHADOW", "true").lower() == "true"
TEST_USER_ID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"
