"""Prevent common credential formats and runtime state from entering tracked files.

Print locations only; never print the credential that triggered a finding.
This complements review and does not establish that every possible secret is absent.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'GitHub token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b',
    'GitLab token': rb'\bglpat-[A-Za-z0-9_-]{20,}\b',
    'Discord webhook': rb'https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{20,}',
    'Slack webhook': rb'https://hooks\.slack\.com/services/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]{20,}',
    'Telegram token': rb'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b',
    'AWS access key': rb'\bAKIA[0-9A-Z]{16}\b',
    'Private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
}


def scan(path, content):
    findings = []
    if re.search(r'(^|/)(?:data|node_modules|__pycache__)/|(^|/)\.env(?:\.|$)|\.(?:db|sqlite3?|log|pem|key|p12|pfx)$', path):
        findings.append((path, 0, 'Runtime state or credential file'))
    for label, pattern in PATTERNS.items():
        for match in re.finditer(pattern, content):
            findings.append((path, content.count(b'\n', 0, match.start()) + 1, label))
    return findings


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    findings = []
    for name in filter(None, names):
        path = ROOT / name
        if path.is_file():
            findings.extend(scan(name, path.read_bytes()))
    for name, line, label in findings:
        print(f'{name}:{line}: {label}')
    if findings:
        raise SystemExit(1)
    print('Repository checks passed: no common credential formats or runtime files found.')


if __name__ == '__main__':
    main()
