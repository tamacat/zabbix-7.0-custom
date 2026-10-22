"""Zabbix 7.0 is AGPL-3.0 (6.0 and earlier are GPL-2.0): the repository must say so wherever it states a license."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS = ["server", "web", "agent2", "proxy"]


def test_license_file_is_the_upstream_agpl_text():
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text and "Version 3" in license_text
    for copying in sorted((REPO_ROOT / "sources").glob("zabbix-*/COPYING")):
        assert copying.read_text(encoding="utf-8") == license_text


def test_readme_states_agpl_not_gpl2():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index("## License"):]
    assert "AGPL-3.0" in section and "GPL-2.0, matching" not in section


def test_every_image_declares_the_license_label():
    for name in COMPONENTS:
        dockerfile = (REPO_ROOT / "docker" / name / "Dockerfile").read_text(encoding="utf-8")
        final_stage = dockerfile[dockerfile.rindex("\nFROM "):]
        assert 'org.opencontainers.image.licenses="AGPL-3.0-only"' in final_stage, name


def test_binary_archives_describe_the_agpl():
    for name in ("THIRD-PARTY-NOTICES.txt", "README-linux.txt", "README-windows.txt"):
        text = (REPO_ROOT / "docker" / "agent2-binaries" / name).read_text(encoding="utf-8")
        assert "AGPL" in text or "Affero" in text, name
