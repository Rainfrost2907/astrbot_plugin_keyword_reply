"""Build a source-only local plugin ZIP with an explicit allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parents[1]
    target = root / "dist" / "astrbot_plugin_keyword_reply.zip"
    target.parent.mkdir(exist_ok=True)
    files = [
        root / name
        for name in [
            "main.py",
            "metadata.yaml",
            "_conf_schema.json",
            "requirements.txt",
            "README.md",
            "CHANGELOG.md",
        ]
    ]
    files.extend((root / "keyword_reply").glob("*.py"))
    files.extend((root / "examples").glob("*.json"))
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, "astrbot_plugin_keyword_reply/" + path.relative_to(root).as_posix())
    print(target)


if __name__ == "__main__":
    main()
