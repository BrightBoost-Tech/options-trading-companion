#!/usr/bin/env python3
import os
import sys
import re

# Patterns that look like hardcoded secrets
# We look for VARIABLE="value" where value is not empty and not a variable reference ($...)
SECRET_PATTERNS = [
    (r'PLAID_SECRET\s*=\s*["\']([^"\'$]+)["\']', "PLAID_SECRET"),
    (r'SUPABASE_SERVICE_ROLE_KEY\s*=\s*["\']([^"\'$]+)["\']', "SUPABASE_SERVICE_ROLE_KEY"),
    (r'QCI_API_TOKEN\s*=\s*["\']([^"\'$]+)["\']', "QCI_API_TOKEN"),
    (r'POLYGON_API_KEY\s*=\s*["\']([^"\'$]+)["\']', "POLYGON_API_KEY"),
    (r'ENCRYPTION_KEY\s*=\s*["\']([^"\'$]+)["\']', "ENCRYPTION_KEY"),
]

# Files/Directories to ignore
IGNORE_DIRS = {
    '.git', '__pycache__', 'node_modules', 'venv', '.next', 'dist', 'build',
    'coverage', '.pytest_cache'
}
IGNORE_FILES = {
    '.env', '.env.example', '.env.local', '.env.test',
    'check_for_plaintext_secrets.py', # This script itself
    'pnpm-lock.yaml', 'package-lock.json', 'yarn.lock'
}

def scan_file(filepath):
    issues = []
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            for pattern, name in SECRET_PATTERNS:
                matches = re.finditer(pattern, content)
                for match in matches:
                    # Check if it's a false positive (e.g. example values)
                    val = match.group(1)
                    if "your_" in val.lower() or "test_" in val.lower() or "example" in val.lower():
                        continue

                    # Calculate line number
                    lineno = content[:match.start()].count('\n') + 1
                    issues.append(f"{filepath}:{lineno} -> Potential hardcoded {name}")
    except Exception as e:
        # print(f"Skipping {filepath}: {e}")
        pass
    return issues

def main():
    root_dir = os.getcwd()
    print(f"Scanning for plaintext secrets in {root_dir}...")

    all_issues = []

    for root, dirs, files in os.walk(root_dir):
        # Filter directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            if file in IGNORE_FILES:
                continue

            filepath = os.path.join(root, file)
            issues = scan_file(filepath)
            all_issues.extend(issues)

    if all_issues:
        print("\n❌ FOUND POTENTIAL SECRETS:")
        for issue in all_issues:
            print(issue)
        print("\nPlease remove hardcoded secrets and use environment variables.")
        sys.exit(1)
    else:
        print("✅ No obvious plaintext secrets found.")
        sys.exit(0)

if __name__ == "__main__":
    main()
