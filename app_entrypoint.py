#!/usr/bin/env python3
"""
Dispatch Railway service roles from environment variables.
"""
import os
import subprocess
import sys


def main() -> int:
    app_role = os.getenv("APP_ROLE", "bot").strip().lower()

    if app_role == "bot":
        command = [sys.executable, "main_multi_symbol.py", "--execute"]
    elif app_role == "daily_report_email":
        command = [sys.executable, "daily_report.py", "--yesterday", "--email"]
        if os.getenv("REPORT_STDOUT", "false").lower() == "true":
            command.append("--stdout")
    elif app_role == "daily_report":
        command = [sys.executable, "daily_report.py", "--yesterday"]
        if os.getenv("REPORT_STDOUT", "true").lower() == "true":
            command.append("--stdout")
    else:
        print(f"Unknown APP_ROLE: {app_role}")
        return 1

    completed = subprocess.run(command)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
