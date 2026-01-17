"""
Security v4: Secrets Audit Utilities

This module provides utilities for:
- Listing all secrets used in the codebase
- Verifying secrets have valid configurations
- Detecting potential hardcoded secrets
- Supporting multiple secrets backends (future: Vault, AWS Secrets Manager)
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum


# =============================================================================
# Configuration
# =============================================================================

class SecretsBackend(Enum):
    """Supported secrets backends."""
    ENV = "env"  # Environment variables (default)
    VAULT = "vault"  # HashiCorp Vault (placeholder)
    AWS_SECRETS_MANAGER = "aws_secrets_manager"  # AWS Secrets Manager (placeholder)


# Get configured backend
SECRETS_MANAGER_BACKEND = SecretsBackend(
    os.getenv("SECRETS_MANAGER_BACKEND", "env")
)


# =============================================================================
# Secret Registry
# =============================================================================

@dataclass
class SecretDefinition:
    """Definition of a secret used in the codebase."""
    name: str
    description: str
    required: bool = True
    category: str = "general"
    example_format: str = ""
    used_in: List[str] = field(default_factory=list)


# Registry of all secrets used
SECRET_REGISTRY: Dict[str, SecretDefinition] = {
    # Supabase
    "SUPABASE_URL": SecretDefinition(
        name="SUPABASE_URL",
        description="Supabase project URL",
        category="supabase",
        example_format="https://<project>.supabase.co",
        used_in=["security/supabase_config.py", "jobs/db.py"]
    ),
    "SUPABASE_JWT_SECRET": SecretDefinition(
        name="SUPABASE_JWT_SECRET",
        description="JWT signing secret for token verification",
        category="supabase",
        example_format="<base64-encoded-secret>",
        used_in=["security/__init__.py"]
    ),
    "SUPABASE_ANON_KEY": SecretDefinition(
        name="SUPABASE_ANON_KEY",
        description="Anonymous key for user-scoped operations",
        category="supabase",
        example_format="eyJ...",
        used_in=["security/supabase_config.py"]
    ),
    "SUPABASE_SERVICE_ROLE_KEY": SecretDefinition(
        name="SUPABASE_SERVICE_ROLE_KEY",
        description="Service role key for admin operations (bypasses RLS)",
        category="supabase",
        example_format="eyJ...",
        used_in=["security/supabase_config.py", "jobs/db.py", "api.py"]
    ),

    # Security
    "ENCRYPTION_KEY": SecretDefinition(
        name="ENCRYPTION_KEY",
        description="Fernet key for token encryption",
        category="security",
        example_format="<32-byte-base64-encoded>",
        used_in=["security/__init__.py"]
    ),
    "TASK_SIGNING_SECRET": SecretDefinition(
        name="TASK_SIGNING_SECRET",
        description="HMAC signing key for task endpoints",
        category="security",
        required=False,
        example_format="<random-hex-string>",
        used_in=["security/task_signing_v4.py"]
    ),
    "TASK_SIGNING_KEYS": SecretDefinition(
        name="TASK_SIGNING_KEYS",
        description="Multiple signing keys for rotation",
        category="security",
        required=False,
        example_format="kid1:secret1,kid2:secret2",
        used_in=["security/task_signing_v4.py"]
    ),
    "CRON_SECRET": SecretDefinition(
        name="CRON_SECRET",
        description="Legacy cron authentication (deprecated)",
        category="security",
        required=False,
        example_format="<random-string>",
        used_in=["security/cron_auth.py", "security/task_signing_v4.py"]
    ),
    "ADMIN_USER_IDS": SecretDefinition(
        name="ADMIN_USER_IDS",
        description="Comma-separated admin user UUIDs",
        category="security",
        required=False,
        example_format="uuid1,uuid2",
        used_in=["security/admin_auth.py"]
    ),

    # External APIs
    "POLYGON_API_KEY": SecretDefinition(
        name="POLYGON_API_KEY",
        description="Polygon.io API key for market data",
        category="external",
        required=False,
        example_format="<api-key>",
        used_in=["market_data.py"]
    ),
    "PLAID_CLIENT_ID": SecretDefinition(
        name="PLAID_CLIENT_ID",
        description="Plaid client ID for brokerage integration",
        category="external",
        required=False,
        example_format="<client-id>",
        used_in=["plaid_service.py"]
    ),
    "PLAID_SECRET": SecretDefinition(
        name="PLAID_SECRET",
        description="Plaid secret for brokerage integration",
        category="external",
        required=False,
        example_format="<secret>",
        used_in=["plaid_service.py"]
    ),

    # OpenAI
    "OPENAI_API_KEY": SecretDefinition(
        name="OPENAI_API_KEY",
        description="OpenAI API key for AI features",
        category="external",
        required=False,
        example_format="sk-...",
        used_in=["services/ai_service.py"]
    ),
}


# =============================================================================
# Audit Functions
# =============================================================================

def list_all_secrets_used() -> Dict[str, SecretDefinition]:
    """
    List all secrets defined in the registry.

    Returns:
        Dict of secret name -> SecretDefinition
    """
    return SECRET_REGISTRY.copy()


def get_secrets_by_category(category: str) -> Dict[str, SecretDefinition]:
    """Get all secrets in a specific category."""
    return {
        name: defn
        for name, defn in SECRET_REGISTRY.items()
        if defn.category == category
    }


def check_secret_configuration() -> Tuple[List[str], List[str], List[str]]:
    """
    Check current secret configuration.

    Returns:
        Tuple of (configured, missing_required, missing_optional)
    """
    configured = []
    missing_required = []
    missing_optional = []

    for name, defn in SECRET_REGISTRY.items():
        value = os.getenv(name)
        if value:
            configured.append(name)
        elif defn.required:
            missing_required.append(name)
        else:
            missing_optional.append(name)

    return configured, missing_required, missing_optional


def print_secrets_audit_report():
    """Print a formatted audit report of all secrets."""
    configured, missing_required, missing_optional = check_secret_configuration()

    print("\n" + "=" * 60)
    print("SECRETS AUDIT REPORT")
    print("=" * 60)

    print(f"\nBackend: {SECRETS_MANAGER_BACKEND.value}")

    # By category
    categories = set(d.category for d in SECRET_REGISTRY.values())
    for cat in sorted(categories):
        cat_secrets = get_secrets_by_category(cat)
        print(f"\n[{cat.upper()}]")
        for name, defn in cat_secrets.items():
            status = "OK" if name in configured else ("MISSING" if defn.required else "not set")
            marker = "X" if name in configured else ("!" if defn.required else "-")
            print(f"  [{marker}] {name}: {defn.description}")

    # Summary
    print("\n" + "-" * 60)
    print(f"Total secrets: {len(SECRET_REGISTRY)}")
    print(f"  Configured: {len(configured)}")
    print(f"  Missing (required): {len(missing_required)}")
    print(f"  Missing (optional): {len(missing_optional)}")

    if missing_required:
        print(f"\n CRITICAL: Missing required secrets: {', '.join(missing_required)}")

    print("=" * 60 + "\n")


# =============================================================================
# Hardcoded Secret Detection
# =============================================================================

# Patterns that might indicate hardcoded secrets
SUSPICIOUS_PATTERNS = [
    # API keys
    (r'["\']sk-[a-zA-Z0-9]{20,}["\']', "Possible OpenAI API key"),
    (r'["\']eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+["\']', "Possible JWT token"),

    # Base64 encoded secrets (at least 32 chars)
    (r'["\'][A-Za-z0-9+/]{32,}={0,2}["\']', "Possible base64-encoded secret"),

    # AWS keys
    (r'AKIA[0-9A-Z]{16}', "Possible AWS access key"),
    (r'["\'][a-zA-Z0-9/+]{40}["\']', "Possible AWS secret key"),

    # Database connection strings
    (r'postgres://[^\s"\']+:[^\s"\']+@', "Database connection string with credentials"),
]

# Files to exclude from scanning
EXCLUDED_PATHS = {
    "__pycache__",
    ".git",
    "node_modules",
    "venv",
    ".env",
    ".env.local",
    ".env.example",
    "test_",  # Test files may have mock secrets
}


def scan_for_hardcoded_secrets(
    root_path: Path,
    extensions: Set[str] = {".py", ".ts", ".js", ".json", ".yaml", ".yml"}
) -> List[Tuple[str, int, str, str]]:
    """
    Scan codebase for potentially hardcoded secrets.

    Args:
        root_path: Root directory to scan
        extensions: File extensions to check

    Returns:
        List of (file_path, line_number, matched_text, description)
    """
    findings = []

    for file_path in root_path.rglob("*"):
        # Skip excluded paths
        if any(excl in str(file_path) for excl in EXCLUDED_PATHS):
            continue

        # Only check specified extensions
        if file_path.suffix not in extensions:
            continue

        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for line_num, line in enumerate(content.split("\n"), 1):
            for pattern, description in SUSPICIOUS_PATTERNS:
                matches = re.findall(pattern, line)
                for match in matches:
                    # Skip if it looks like an env var reference
                    if "os.getenv" in line or "os.environ" in line:
                        continue
                    if "process.env" in line:
                        continue

                    findings.append((
                        str(file_path.relative_to(root_path)),
                        line_num,
                        match[:50] + "..." if len(match) > 50 else match,
                        description
                    ))

    return findings


def print_hardcoded_secrets_report(root_path: Optional[Path] = None):
    """Print a report of potentially hardcoded secrets."""
    if root_path is None:
        # Default to packages/quantum
        root_path = Path(__file__).resolve().parent.parent

    findings = scan_for_hardcoded_secrets(root_path)

    print("\n" + "=" * 60)
    print("HARDCODED SECRETS SCAN")
    print("=" * 60)

    if not findings:
        print("\n No potential hardcoded secrets found.")
    else:
        print(f"\n Found {len(findings)} potential issues:\n")
        for file_path, line_num, match, desc in findings:
            print(f"  {file_path}:{line_num}")
            print(f"    {desc}")
            print(f"    Match: {match}")
            print()

    print("=" * 60 + "\n")


# =============================================================================
# CLI Interface
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "audit":
            print_secrets_audit_report()
        elif command == "scan":
            print_hardcoded_secrets_report()
        elif command == "list":
            for name, defn in list_all_secrets_used().items():
                print(f"{name}: {defn.description}")
        else:
            print(f"Unknown command: {command}")
            print("Usage: python secrets_audit.py [audit|scan|list]")
    else:
        print_secrets_audit_report()
        print_hardcoded_secrets_report()
