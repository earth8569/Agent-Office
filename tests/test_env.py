from __future__ import annotations

import os
import unittest
from pathlib import Path
from uuid import uuid4

from agent_office.env import load_dotenv


class EnvTests(unittest.TestCase):
    def test_load_dotenv_does_not_override_existing_env(self) -> None:
        key = f"AGENT_OFFICE_TEST_{uuid4().hex}"
        path = Path("data") / f"test-env-{uuid4().hex}.env"
        path.write_text(f"{key}=from_file\n", encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        self.addCleanup(lambda: os.environ.pop(key, None))
        os.environ[key] = "existing"

        load_dotenv(path)

        self.assertEqual(os.environ[key], "existing")

    def test_load_dotenv_loads_missing_values(self) -> None:
        key = f"AGENT_OFFICE_TEST_{uuid4().hex}"
        path = Path("data") / f"test-env-{uuid4().hex}.env"
        path.write_text(f"{key}=from_file\n", encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        self.addCleanup(lambda: os.environ.pop(key, None))

        load_dotenv(path)

        self.assertEqual(os.environ[key], "from_file")


if __name__ == "__main__":
    unittest.main()
