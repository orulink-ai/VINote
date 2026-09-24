from app.services.note_origin_service import read_origin, record_origin


def test_origin_is_immutable_and_corrupt_metadata_is_unknown(tmp_path):
    record_origin(tmp_path, 'mobile')
    record_origin(tmp_path, 'desktop')
    assert read_origin(tmp_path) == 'mobile'
    (tmp_path / 'generation_client').write_bytes(b'\xff\xfe')
    assert read_origin(tmp_path) is None
    (tmp_path / 'generation_client').unlink()
    assert read_origin(tmp_path) is None
