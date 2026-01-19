#!/usr/bin/env python
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    common_args = [
        "uv",
        "pip",
        "compile",
        "--quiet",
        "--generate-hashes",
        "requirements.in",
        *sys.argv[1:],
    ]
    run = partial(subprocess.run, check=True)

    # Define Python versions and Django versions
    python_versions = ["3.10", "3.11", "3.12", "3.13", "3.14"]
    django_versions = {
        "42": "Django>=4.2a1,<5.0",
        "50": "Django>=5.0a1,<5.1",
        "51": "Django>=5.1a1,<5.2",
        "52": "Django>=5.2.9,<5.3",
        "60": "Django>=6.0a1,<6.1",
    }

    # Define the specific combinations to run
    # Format: (python_version, django_version)
    combinations = [
        ("3.10", "42"),
        ("3.10", "50"),
        ("3.10", "51"),
        ("3.10", "52"),
        ("3.11", "42"),
        ("3.11", "50"),
        ("3.11", "51"),
        ("3.11", "52"),
        ("3.12", "42"),
        ("3.12", "50"),
        ("3.12", "51"),
        ("3.12", "52"),
        ("3.13", "51"),
        ("3.13", "52"),
        ("3.13", "60"),
        ("3.14", "51"),
        ("3.14", "52"),
        ("3.14", "60"),
    ]

    # Run the combinations
    for py_version, dj_version in combinations:
        output_file = f"py{py_version.replace('.', '')}-django{dj_version}.txt"
        django_constraint = django_versions[dj_version]

        with tempfile.NamedTemporaryFile("w", delete=False) as constraint_file:
            constraint_file.write(f"{django_constraint}\n")
            constraint_path = constraint_file.name

        try:
            run(
                [
                    *common_args,
                    "--constraints",
                    constraint_path,
                    "--python",
                    py_version,
                    "--output-file",
                    output_file,
                ]
            )
        finally:
            os.unlink(constraint_path)
