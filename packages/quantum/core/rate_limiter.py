from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared Limiter Instance
# We use key_func=get_remote_address for simple IP-based limiting.
# In a real production behind load balancers, you might need X-Forwarded-For support via middleware/config.
limiter = Limiter(key_func=get_remote_address)
