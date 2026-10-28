from html_sanitizer import sanitize_document_html


def test_document_sanitizer_preserves_passive_markup_and_styles():
    source = '<div style="padding: 10px; color: #000"><h2>Draft</h2><p><strong>Notice</strong></p></div>'
    cleaned = sanitize_document_html(source)
    assert '<h2>Draft</h2>' in cleaned
    assert '<strong>Notice</strong>' in cleaned
    assert 'padding: 10px' in cleaned


def test_document_sanitizer_removes_active_markup_event_handlers_and_urls():
    source = (
        '<div onclick="alert(1)" style="color:red; background:url(javascript:alert(1))">'
        'Safe text<img src="x" onerror="alert(2)">'
        '<script>alert(3)</script><iframe src="https://evil.example"></iframe>'
        '<p style="display:none; color: #111">Visible draft</p>'
        '<a href="javascript:alert(4)">Link text</a></div>'
    )
    cleaned = sanitize_document_html(source)
    lowered = cleaned.lower()
    assert '<script' not in lowered and '<iframe' not in lowered and '<img' not in lowered
    assert '<a ' not in lowered and 'href=' not in lowered and 'onclick=' not in lowered
    assert 'onerror=' not in lowered and 'javascript:' not in lowered and 'url(' not in lowered
    assert 'display: none' not in lowered
    assert 'Safe text' in cleaned and 'Visible draft' in cleaned
    assert '&lt;' not in cleaned  # benign plain text remains readable
