from unittest.mock import MagicMock, patch

from dnsrecon.lib.yandexenum import scrape_yandex


def test_scrape_yandex_paginates_with_page_parameter():
    """Each iteration must request a distinct Yandex page (p=N), not the same URL."""
    responses = []
    for page in range(8):
        resp = MagicMock()
        resp.text = f'<a href="https://host{page}.example.com/">link</a>'
        responses.append(resp)

    with patch('dnsrecon.lib.yandexenum.httpx.Client') as mock_client_cls, \
            patch('dnsrecon.lib.yandexenum.time.sleep'):
        client = mock_client_cls.return_value.__enter__.return_value
        client.get.side_effect = responses

        result = scrape_yandex('example.com')

    assert client.get.call_count == 8
    requested_urls = [call.args[0] for call in client.get.call_args_list]
    for page in range(8):
        assert f'p={page}' in requested_urls[page]
        assert 'site%3Aexample.com' in requested_urls[page]

    assert 'host0.example.com' in result
    assert 'host7.example.com' in result
