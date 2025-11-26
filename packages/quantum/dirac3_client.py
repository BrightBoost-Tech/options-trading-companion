import os

class Dirac3Client:
    def __init__(self):
        self.api_key = os.getenv("DIRAC3_API_KEY")
        self.endpoint = os.getenv("DIRAC3_ENDPOINT", "https://api.dirac3.example.com")
        self.enabled = bool(self.api_key)

    def optimize_portfolio(self, positions, constraints):
        if not self.enabled:
            # Fallback to existing optimizer or raise a clear error
            return None
        # TODO: implement real HTTP call once API spec is available
        # return requests.post(...).json()
