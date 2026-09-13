"""Exercise the launcher without touching real Docker or starting another API."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("docker_running", [False, True])
def test_launcher_recovers_docker_and_checks_dependencies(tmp_path, docker_running):
    (tmp_path / "scripts").mkdir()
    shutil.copy(Path(__file__).parents[1] / "scripts/start-local.sh", tmp_path / "scripts")
    commands = tmp_path / "bin"
    commands.mkdir()
    (tmp_path / "venv/bin").mkdir(parents=True)

    def executable(path, body):
        path.write_text("#!/bin/bash\n" + body)
        path.chmod(0o755)

    executable(commands / "docker", '''
if [[ "$1" == "info" ]]; then
  [[ -f daemon-running ]]
else
  echo "docker $*" >> calls
fi
''')
    executable(commands / "uname", 'echo Darwin\n')
    executable(commands / "open", 'echo "open $*" >> calls\ntouch daemon-running\n')
    executable(tmp_path / "venv/bin/python", 'echo "python $*" >> calls\n')
    if docker_running:
        (tmp_path / "daemon-running").touch()
    env = dict(os.environ, PATH=f"{commands}:{os.environ['PATH']}")
    result = subprocess.run(
        ["bash", str(tmp_path / "scripts/start-local.sh"), "--dependencies-only"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "calls").read_text()
    assert ("open -a Docker" in calls) == (not docker_running)
    assert "--wait --wait-timeout 90 postgres redis" in calls
    assert "python -m scripts.check_dependencies" in calls
    assert "uvicorn" not in calls
