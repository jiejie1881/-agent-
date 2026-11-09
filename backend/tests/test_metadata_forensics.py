import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from tools.metadata_forensics import FIELDS, MetadataMismatch, assert_same, metadata, snapshot_fixture


@pytest.mark.parametrize("field", FIELDS)
def test_every_original_field_still_rejects_and_preserves_exact_delta(field):
    before = dict.fromkeys(FIELDS, 100)
    after = {**before, field: 101}
    with pytest.raises(MetadataMismatch) as caught:
        assert_same("source_directory", before, after)
    assert caught.value.before == before
    assert caught.value.after == after
    assert caught.value.fields[field] == {"expected": 100, "actual": 101, "delta": 1, "changed": True}
    assert len(caught.value.fields) == 10


def test_unchanged_metadata_is_exact_not_rounded():
    values = {key: 1792999536028116700 for key in FIELDS}
    assert metadata(SimpleNamespace(**values)) == values
    assert_same("same", values, values.copy())


def test_missing_metadata_field_never_accepted():
    with pytest.raises(ValueError):
        assert_same("missing", {}, {})


def test_existing_destination_rejected_before_source_open(tmp_path):
    destination = tmp_path / "copy"
    destination.mkdir()
    with patch("tools.metadata_forensics.os.open", side_effect=AssertionError("source must not open")):
        with pytest.raises(FileExistsError):
            snapshot_fixture(tmp_path / "not-opened", destination, fixture_root=tmp_path, names=["synthetic.bin"], quiescent=True)


def test_no_quiescence_stops_before_source_access(tmp_path):
    with patch("tools.metadata_forensics.os.open", side_effect=AssertionError("source must not open")):
        with pytest.raises(RuntimeError, match="quiescence"):
            snapshot_fixture(tmp_path / "source", tmp_path / "copy", fixture_root=tmp_path, names=["synthetic.bin"])


def test_path_escape_stops_before_access(tmp_path):
    with pytest.raises(ValueError):
        snapshot_fixture(tmp_path.parent, tmp_path / "copy", fixture_root=tmp_path, names=["x"])


def test_native_platform_never_emulated(tmp_path):
    if sys.platform == "linux" and hasattr(os, "O_NOATIME"):
        pytest.skip("This assertion targets native unsupported platforms")
    with pytest.raises(RuntimeError, match="O_NOATIME_unavailable"):
        snapshot_fixture(tmp_path / "source", tmp_path / "copy", fixture_root=tmp_path, names=["synthetic.bin"], quiescent=True)
