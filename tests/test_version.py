import shutil
import subprocess
import sys
from pathlib import Path


def project_copy(tmp_path):
    # A fixed release fixture keeps these tests valid after future real version bumps.
    fixtures = {
        "metadata.yaml": "name: sample\nversion: 2.0.0\n",
        "pyproject.toml": '[project]\nname = "sample"\nversion = "2.0.0"\n',
        "README.md": "# Example\n\n当前版本：`2.0.0`。\n",
        "CHANGELOG.md": "# 更新记录\n\n## 2.0.0 — 2026-09-30\n\n- Initial release\n",
        "keyword_reply/version.py": '__version__ = "2.0.0"\n',
    }
    for name, content in fixtures.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(Path("scripts/version.py"), tmp_path / "scripts/version.py")
    return tmp_path


def run(root, *args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "scripts.version", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_release_check_catches_a_stale_metadata_version(tmp_path):
    root = project_copy(tmp_path)
    assert run(root, "--check").returncode == 0
    path = root / "metadata.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("version: 2.0.0", "version: 1.0.0"),
        encoding="utf-8",
    )
    assert run(root, "--check").returncode != 0


def test_bump_updates_all_release_files_and_requires_advancing(tmp_path):
    root = project_copy(tmp_path)
    result = run(root, "2.0.1", "--note", "修复关键词匹配")
    assert result.returncode == 0, result.stderr
    assert run(root, "--check").returncode == 0
    assert "2.0.1" in (root / "metadata.yaml").read_text(encoding="utf-8")
    assert "2.0.1" in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "修复关键词匹配" in (root / "CHANGELOG.md").read_text(encoding="utf-8")
    before = (root / "metadata.yaml").read_bytes()
    assert run(root, "2.0.0", "--note", "cannot downgrade").returncode != 0
    assert (root / "metadata.yaml").read_bytes() == before
