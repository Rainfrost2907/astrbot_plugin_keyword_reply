"""Check releases, or advance all version files with one command."""

import argparse
import re
import tomllib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_versions(root=ROOT):
    paths = {
        name: (root / name).read_text(encoding="utf-8")
        for name in [
            "keyword_reply/version.py",
            "metadata.yaml",
            "pyproject.toml",
            "README.md",
            "CHANGELOG.md",
        ]
    }
    versions = {
        "keyword_reply/version.py": re.search(
            r'__version__ = "([^"]+)"', paths["keyword_reply/version.py"]
        )[1],
        "metadata.yaml": re.search(r"(?m)^version: (\S+)$", paths["metadata.yaml"])[1],
        "pyproject.toml": tomllib.loads(paths["pyproject.toml"])["project"]["version"],
        "README.md": re.search(r"当前版本：`([^`]+)`", paths["README.md"])[1],
        "CHANGELOG.md": re.search(r"(?m)^## (\d+\.\d+\.\d+)", paths["CHANGELOG.md"])[1],
    }
    return paths, versions


def check(root=ROOT):
    _, versions = read_versions(root)
    if len(set(versions.values())) != 1:
        raise ValueError("版本不一致：" + str(versions))
    return next(iter(versions.values()))


def advance(version, note, root=ROOT):
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise ValueError("版本须为 X.Y.Z")
    if not note or not note.strip() or "\n" in note or "\r" in note:
        raise ValueError("需要一行修改说明 --note")
    old = check(root)
    if tuple(map(int, version.split("."))) <= tuple(map(int, old.split("."))):
        raise ValueError("新版本必须高于当前版本")
    paths, _ = read_versions(root)
    paths["keyword_reply/version.py"] = f'__version__ = "{version}"\n'
    paths["metadata.yaml"] = re.sub(
        r"(?m)^version: \S+$", f"version: {version}", paths["metadata.yaml"]
    )
    paths["pyproject.toml"] = re.sub(
        r'(?m)^version = "[^"]+"$', f'version = "{version}"', paths["pyproject.toml"], count=1
    )
    paths["README.md"] = paths["README.md"].replace(
        f"当前版本：`{old}`", f"当前版本：`{version}`", 1
    )
    paths["CHANGELOG.md"] = paths["CHANGELOG.md"].replace(
        "# 更新记录\n",
        f"# 更新记录\n\n## {version} — {date.today().isoformat()}\n\n- {note.strip()}\n",
        1,
    )
    for name, content in paths.items():
        (root / name).write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--note")
    args = parser.parse_args()
    try:
        if args.check and args.version:
            raise ValueError("--check 不接受新版本")
        if not args.check:
            advance(args.version or "", args.note)
        print("Version: " + check())
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
