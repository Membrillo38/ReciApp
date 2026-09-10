#!/usr/bin/env python3
"""Inject /etc/reciapp/recipe-backend.env into Coolify application id=1.

Coolify encrypts env values. Plain SQL inserts make deploys fail with
DecryptException. This wrapper runs the Eloquent writer.
"""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("fix_coolify_env_encrypted.py")), run_name="__main__")
