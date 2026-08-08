"""Regression tests for remaining enum bugs."""
from unittest.mock import MagicMock, patch

from dnsrecon import cli


def test_se_result_process_includes_aaaa():
    with patch('dnsrecon.lib.dnshelper.DnsHelper') as mock_dns_helper:
        mock_instance = mock_dns_helper.return_value
        mock_instance.get_ip.return_value = [
            ('A', 'zonetransfer.me', '192.0.2.1'),
            ('CNAME', 'zonetransfer.me', 'some.domain.com'),
            ('AAAA', 'zonetransfer.me', '2001:db8::1'),
        ]
        results = cli.se_result_process(mock_instance, 'zonetransfer.me', ['zonetransfer.me'])
        assert len(results) == 3
        assert results[2]['type'] == 'AAAA'
        assert results[2]['address'] == '2001:db8::1'


def test_brute_tlds_uses_time_module_for_duration_estimate():
    """TLD brute force must not crash with NameError on time (missing import)."""
    res = MagicMock()
    res.get_ip.return_value = []
    fake_psl = 'com\nnet\norg\n'

    with patch('dnsrecon.cli.httpx.get') as mock_get, \
            patch('dnsrecon.cli.futures.ThreadPoolExecutor') as mock_executor:
        mock_get.return_value.text = fake_psl
        mock_executor.return_value.__enter__.return_value.submit = MagicMock()
        mock_executor.return_value.__enter__.return_value.__exit__ = MagicMock(return_value=False)
        with patch('dnsrecon.cli.futures.as_completed', return_value=[]):
            result = cli.brute_tlds(res, 'example', verbose=False, thread_num=1)

    assert result == []
