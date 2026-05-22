from pathlib import Path


def _html() -> str:
    return Path('app/templates/experiment.html').read_text(encoding='utf-8')


def test_loading_copy_exists():
    html = _html()
    assert '正在识别画面对象……' in html
    assert '正在提取图层，可能需要 20–60 秒……' in html


def test_empty_objects_has_manual_guidance():
    html = _html()
    assert '没有自动识别到可用对象，可以重新上传更清晰图片，或使用手动框选模式。' in html


def test_duplicate_manual_button_id_removed():
    html = _html()
    assert html.count('id="manualModeBtn"') == 0
    assert 'manualModeFromObjectPanel' in html
    assert 'manualModeFromNotice' in html


def test_analyze_comp_disabled_before_save():
    html = _html()
    assert "id='analyzeComp' disabled" in html
    assert 'S.isSaved=true' in html


def test_debug_collapsed_by_default():
    html = _html()
    assert "<details id='devDebug'><summary>开发者调试信息</summary>" in html
