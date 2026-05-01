from pathlib import Path


def test_openapi_plugin_file_exists() -> None:
    assert Path('docs/openapi.plugin.yaml').exists()
