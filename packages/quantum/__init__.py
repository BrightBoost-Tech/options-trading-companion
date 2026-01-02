import sys

# Quantum stack requires Python < 3.14 due to qci-client compatibility.
# qci-client binaries are not yet available for Python 3.14+.
if sys.version_info >= (3, 14):
    raise RuntimeError("Quantum stack requires Python 3.11 or 3.12 due to qci-client compatibility.")
