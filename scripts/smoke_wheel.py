"""Install one built wheel into a fresh environment and test its public CLI.

Run from the checkout: python scripts/smoke_wheel.py dist/<wheel>.whl
All installation/runtime files live in a temporary directory outside the repo.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import venv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    if wheel.suffix != ".whl":
        parser.error("provide a built .whl distribution")
    source = Path(__file__).resolve().parents[1] / "src" / "mboxer"
    expected_migrations = {path.stem for path in (source / "db" / "migrations").glob("*.sql")}
    expected_example = (source / "defaults.yaml").read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="mboxer-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        executable = scripts / ("mboxer.exe" if os.name == "nt" else "mboxer")
        work = root / "work"
        work.mkdir()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)

        def run(*command: str, succeeds: bool = True) -> subprocess.CompletedProcess[str]:
            result = subprocess.run(
                command, cwd=work, env=env, text=True, capture_output=True, timeout=180,
            )
            if succeeds and result.returncode:
                raise RuntimeError(f"Wheel smoke command failed: {command}\n{result.stdout}\n{result.stderr}")
            return result

        run(str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", str(wheel))
        # -I ignores the caller's import paths; verify the imported distribution
        # belongs to the fresh environment, not an editable source checkout.
        check = run(str(python), "-I", "-c", "import mboxer; print(mboxer.__file__)")
        imported = Path(check.stdout.strip()).resolve()
        if not imported.is_relative_to(environment.resolve()):
            raise RuntimeError(f"Imported outside the isolated environment: {imported}")
        run(str(executable), "--help")
        example = run(str(executable), "config-example")
        if example.stdout != expected_example:
            raise RuntimeError("Bundled configuration example was not installed")
        run(str(executable), "init-db")
        run(str(python), "-I", "-m", "mboxer", "init-db")  # migration idempotence
        run(str(executable), "account", "add", "smoke")
        listing = run(str(executable), "account", "list")
        if "smoke" not in listing.stdout:
            raise RuntimeError("Account command did not persist its state")
        with sqlite3.connect(work / "var" / "mboxer.sqlite") as conn:
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            installed = set(run(
                str(python), "-I", "-c",
                "from importlib.resources import files; "
                "print('\\n'.join(sorted(p.name[:-4] for p in files('mboxer.db.migrations').iterdir() "
                "if p.name.endswith('.sql'))))",
            ).stdout.splitlines())
            if not applied or applied != installed or installed != expected_migrations:
                raise RuntimeError(
                    f"Installed migrations incomplete: applied={applied}, "
                    f"installed={installed}, source={expected_migrations}"
                )
        missing = run(
            str(executable), "init-db", "--config", "missing.yaml", succeeds=False,
        )
        if missing.returncode == 0 or "Config file not found" not in missing.stderr:
            raise RuntimeError("Explicit missing configuration silently fell back")
        print(f"Wheel smoke passed: {wheel.name}")


if __name__ == "__main__":
    main()
