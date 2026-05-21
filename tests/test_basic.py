from pathlib import Path

from po_file_search.config import MountConfig
from po_file_search.indexer import connect, index_root
from po_file_search.mounter import build_linux_mount_command, mount_point_for
from po_file_search.platforms import SupportedOS
from po_file_search.searcher import search
from po_file_search.sender import send_purchase_file
from po_file_search.config import AppConfig, DownloadConfig


def test_mount_point_by_os():
    cfg = MountConfig(
        name="采购共享",
        server="nas.local",
        share="purchase",
        mount_point_linux="/mnt/purchase",
        mount_point_macos="/Volumes/purchase",
    )
    assert mount_point_for(cfg, SupportedOS.LINUX) == Path("/mnt/purchase")
    assert mount_point_for(cfg, SupportedOS.MACOS) == Path("/Volumes/purchase")


def test_linux_command_contains_readonly_and_smb_version(tmp_path):
    cfg = MountConfig(
        name="采购共享",
        server="nas.local",
        share="purchase",
        mount_point_linux="/mnt/purchase",
        mount_point_macos="/Volumes/purchase",
        smb_version="3.0",
        readonly=True,
    )
    command = build_linux_mount_command(cfg, tmp_path / "cred")
    assert command[:4] == ["mount", "-t", "cifs", "//nas.local/purchase"]
    assert "ro" in command[-1]
    assert "vers=3.0" in command[-1]


def test_index_and_search(tmp_path):
    root = tmp_path / "purchase"
    folder = root / "华东" / "合同"
    folder.mkdir(parents=True)
    target = folder / "比亚迪电池采购合同-2024.pdf"
    target.write_text("demo", encoding="utf-8")

    db = tmp_path / "index.sqlite"
    with connect(db) as con:
        count = index_root(con, "采购共享", root, set())
    assert count == 1

    rows = search(db, "比亚迪 电池 合同", 10)
    assert len(rows) == 1
    assert rows[0]["file_name"] == "比亚迪电池采购合同-2024.pdf"

    target.unlink()
    with connect(db) as con:
        count = index_root(con, "采购共享", root, set())
    assert count == 0
    assert search(db, "比亚迪 电池 合同", 10) == []


def test_send_purchase_file_generates_link(tmp_path):
    root = tmp_path / "purchase"
    root.mkdir()
    target = root / "报价单.xlsx"
    target.write_text("demo", encoding="utf-8")
    db = tmp_path / "index.sqlite"
    with connect(db) as con:
        index_root(con, "采购共享", root, set())
    rows = search(db, "报价单", 10)

    config = AppConfig(
        mounts=[],
        index_db=str(db),
        scan_roots=[],
        ignored_dirs=set(),
        download=DownloadConfig(base_url="http://127.0.0.1:18765", token_ttl_minutes=30),
    )
    result = send_purchase_file(config, int(rows[0]["id"]), channel="link", user_id="u1")
    assert result["sent"] is False
    assert str(result["download_url"]).startswith("http://127.0.0.1:18765/download/")
