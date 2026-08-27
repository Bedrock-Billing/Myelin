import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from myelin.helpers.cms_downloader import CMSDownloader


def make_zip(path: Path, names: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, f"contents of {name}")
    return path


def downloader(tmp_path: Path) -> CMSDownloader:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    return CMSDownloader(jars_dir=str(tmp_path / "jars"), download_dir=str(downloads))


def test_msdrg_versions_are_compared_as_tuples() -> None:
    assert CMSDownloader._msdrg_version("Version 43.10", "unused") == (43, 10)
    assert CMSDownloader._msdrg_version("Version 43.10", "unused") > (
        CMSDownloader._msdrg_version("Version 43.9", "unused")
    )


def test_discovery_selects_highest_version_not_first_link(
    tmp_path, monkeypatch
) -> None:
    instance = downloader(tmp_path)
    pages = {
        instance.IOCE_URL: """
            <a href='/old-java-standalone'>I/OCE Java Standalone Jar V271.R2</a>
            <a href='/new-java-standalone'>I/OCE Java Standalone Jar V272.R0</a>
        """,
        instance.HHAG_URL: """
            <a href='/files/zip/jan-2026-hh-pps-grouper-software.zip'>old</a>
            <a href='/files/zip/oct-2026-hh-pps-grouper-software.zip'>new</a>
        """,
        instance.CMG_URL: """
            <a href='/files/zip/cmg-version-540-final.zip'>old</a>
            <a href='/files/zip/cmg-version-550-final.zip'>new</a>
        """,
    }
    monkeypatch.setattr(
        instance,
        "_get_soup",
        lambda url: BeautifulSoup(pages[url], "html.parser"),
    )

    assert instance._discover_ioce() == "/new-java-standalone"
    assert "oct-2026" in instance._discover_hhag()
    assert "version-550" in instance._discover_cmg()


def test_changed_release_replaces_superseded_jar_and_records_state(
    tmp_path, monkeypatch
) -> None:
    instance = downloader(tmp_path)
    instance.jars_dir.mkdir()
    old_jar = instance.jars_dir / "ioce-standalone-27.1.0.7.jar"
    old_jar.write_text("old")
    package = make_zip(
        instance.download_dir / "ioce.zip", ["lib/ioce-standalone-27.2.0.5.jar"]
    )
    monkeypatch.setattr(instance, "_download_ioce", lambda: package)

    assert instance._install_zip_component(
        "ioce", instance._download_ioce, lambda: "/ioce-v272.zip", False
    )
    assert not old_jar.exists()
    assert (instance.jars_dir / "ioce-standalone-27.2.0.5.jar").exists()
    assert instance._release_state["ioce"] == "/ioce-v272.zip"
    assert instance._load_release_state()["ioce"] == "/ioce-v272.zip"


def test_invalid_new_package_does_not_remove_existing_jar(tmp_path) -> None:
    instance = downloader(tmp_path)
    instance.jars_dir.mkdir()
    old_jar = instance.jars_dir / "ioce-standalone-27.1.0.7.jar"
    old_jar.write_text("old")
    package = make_zip(instance.download_dir / "bad.zip", ["unrelated.jar"])

    assert not instance._extract_jars_from_zip(
        package,
        "ioce",
        wanted_jars=instance.REQUIRED_JARS["ioce"],
        replace_existing=True,
    )
    assert old_jar.read_text() == "old"


def test_current_release_skips_download(tmp_path) -> None:
    instance = downloader(tmp_path)
    instance.jars_dir.mkdir()
    (instance.jars_dir / "HomeHealth.jar").write_text("current")
    instance._release_state["hhag"] = "/hhag-current.zip"
    called = False

    def should_not_download():
        nonlocal called
        called = True
        return None

    assert instance._install_zip_component(
        "hhag", should_not_download, lambda: "/hhag-current.zip", False
    )
    assert not called
