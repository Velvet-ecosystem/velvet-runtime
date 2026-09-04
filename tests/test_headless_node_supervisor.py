import json
import subprocess
from pathlib import Path

import pytest

from services.headless_node_supervisor import (
    HEADLESS_STATUS_SCHEMA,
    HeadlessNodeConfig,
    HeadlessNodeConfigError,
    HeadlessNodeSupervisor,
)


ROOT = Path(__file__).resolve().parents[1]


def mapping(root, storage_path):
    return {
        "schema": "velvet.runtime.headless_node.v1",
        "node_id": "velour-lyra-1",
        "body_id": "velvet-body",
        "organ": "velour",
        "state_path": str(root / "status.json"),
        "heartbeat_seconds": 5.0,
        "body_verified": True,
        "continuity_verified": True,
        "storage_paths": [
            {
                "resource_id": "storage.library",
                "path": str(storage_path),
                "scope": "attached",
                "capabilities": ["library.archive", "library.retrieve"],
            }
        ],
        "extra_resources": [],
        "headless": True,
        "ui_present": False,
        "canonical": False,
        "grants_authority": False,
        "grants_execution": False,
        "grants_actuation": False,
        "authority": "none",
    }


def write_config(tmp_path, value):
    path = tmp_path / "node.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_headless_node_observation_includes_declared_storage(tmp_path):
    storage = tmp_path / "library"
    storage.mkdir()
    config_path = write_config(tmp_path, mapping(tmp_path, storage))
    config = HeadlessNodeConfig.load(config_path.resolve())
    snapshot = HeadlessNodeSupervisor(config).observe_once(now=123.0)

    assert snapshot["schema"] == HEADLESS_STATUS_SCHEMA
    assert snapshot["node_id"] == "velour-lyra-1"
    assert snapshot["organ"] == "velour"
    assert snapshot["headless"] is True
    assert snapshot["ui_present"] is False
    assert snapshot["canonical"] is False
    assert snapshot["authority"] == "none"
    assert snapshot["grants_execution"] is False
    assert snapshot["grants_actuation"] is False

    resources = {item["resource_id"]: item for item in snapshot["resources"]}
    assert "memory.ram" in resources
    assert "compute.logical-cpu" in resources
    assert "storage.library" in resources
    assert resources["storage.library"]["scope"] == "attached"
    assert resources["storage.library"]["authority"] == "none"

    persisted = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert persisted == snapshot
    assert config.state_path.stat().st_mode & 0o077 == 0


def test_missing_declared_storage_is_not_invented(tmp_path):
    missing = tmp_path / "not-mounted"
    config_path = write_config(tmp_path, mapping(tmp_path, missing))
    config = HeadlessNodeConfig.load(config_path.resolve())
    snapshot = HeadlessNodeSupervisor(config).observe_once(now=10.0)

    ids = {item["resource_id"] for item in snapshot["resources"]}
    assert "storage.library" not in ids


def test_config_rejects_ui_or_authority_promotion(tmp_path):
    storage = tmp_path / "library"
    storage.mkdir()
    unsafe = mapping(tmp_path, storage)
    unsafe["ui_present"] = True
    with pytest.raises(HeadlessNodeConfigError, match="ui_present"):
        HeadlessNodeConfig.load(write_config(tmp_path, unsafe).resolve())

    unsafe = mapping(tmp_path, storage)
    unsafe["authority"] = "court"
    with pytest.raises(HeadlessNodeConfigError, match="authority"):
        HeadlessNodeConfig.load(write_config(tmp_path, unsafe).resolve())


def test_example_is_headless_and_uses_existing_body_id():
    raw = json.loads(
        (ROOT / "config" / "headless-velour-lyra.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw["body_id"] == "velvet-body"
    assert raw["headless"] is True
    assert raw["ui_present"] is False
    assert raw["authority"] == "none"


def test_systemd_unit_has_no_graphical_or_network_listener_dependency():
    text = (
        ROOT / "deploy" / "headless" / "systemd" / "velvet-headless-node.service"
    ).read_text(encoding="utf-8")
    assert "graphical.target" not in text
    assert "Display" not in text
    assert "RestrictAddressFamilies=AF_UNIX" in text
    assert "NoNewPrivileges=true" in text


def test_buildroot_init_script_is_shell_syntax_valid():
    script = ROOT / "deploy" / "headless" / "buildroot" / "S70velvet-node"
    completed = subprocess.run(
        ["sh", "-n", str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
