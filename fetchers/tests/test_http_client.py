import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class HttpPolicyTests(unittest.TestCase):
    def policy(self, **kwargs):
        from src.http_client import HttpPolicy
        return HttpPolicy(wait=Mock(), jitter=lambda: 0, **kwargs)

    def response(self, code, headers=None):
        return Mock(status_code=code, headers=headers or {})

    def test_retry_transient_only_with_waits(self):
        p = self.policy()
        get = Mock(side_effect=[requests.Timeout('secret'), self.response(503), self.response(200)])
        self.assertEqual(p.get('https://www.cwa.gov.tw/a', transport=get).status_code, 200)
        self.assertEqual([c.args[0] for c in p.wait.call_args_list], [2, 5])
        self.assertEqual(get.call_count, 3)

    def test_404_and_auth_not_retried(self):
        for code in (404, 410, 401, 403):
            p = self.policy()
            get = Mock(return_value=self.response(code))
            self.assertEqual(p.get('https://www.cwa.gov.tw/a', transport=get).status_code, code)
            self.assertEqual(get.call_count, 1)

    def test_exhaustion_is_sanitized(self):
        from src.http_client import HttpFailure
        p = self.policy()
        with self.assertRaises(HttpFailure) as caught:
            p.get('https://opendata.cwa.gov.tw/a', transport=Mock(side_effect=requests.Timeout('Authorization=secret')))
        self.assertNotIn('secret', str(caught.exception))

    def test_request_budget_includes_retries_and_cwa_hosts_share_it(self):
        from src.http_client import SourceBudgetExceeded
        p = self.policy(max_requests=2)
        get = Mock(return_value=self.response(200))
        p.get('https://www.cwa.gov.tw/a', transport=get)
        p.get('https://opendata.cwa.gov.tw/a', transport=get)
        with self.assertRaises(SourceBudgetExceeded):
            p.get('https://www.cwa.gov.tw/b', transport=get)
        self.assertEqual(get.call_count, 2)

    def test_deadline_and_retry_after_cap(self):
        from src.http_client import SourceBudgetExceeded, HttpFailure
        clock = Mock(side_effect=[0, 100])
        p = self.policy(clock=clock, max_seconds=10)
        get = Mock(return_value=self.response(200))
        p.get('https://example.com/a', transport=get)
        with self.assertRaises(SourceBudgetExceeded):
            p.get('https://example.com/b', transport=get)
        p = self.policy()
        with self.assertRaises(HttpFailure):
            p.get('https://example.com/a', transport=Mock(return_value=self.response(429, {'Retry-After': '120'})))
        p.wait.assert_not_called()

    def test_retry_after_honoured_and_redirects_counted(self):
        p = self.policy()
        get = Mock(side_effect=[self.response(429, {'Retry-After': '7'}), self.response(200)])
        p.get('https://example.com/a', transport=get)
        p.wait.assert_called_once_with(7)
        p = self.policy(max_requests=1)
        from src.http_client import SourceBudgetExceeded
        with self.assertRaises(SourceBudgetExceeded):
            p.get('https://example.com/a', transport=Mock(return_value=self.response(302, {'Location': '/b'})))

    def test_streaming_history_threads_share_the_same_source_budget(self):
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from unittest.mock import patch
        from src.http_client import _policy, http_get, SourceBudgetExceeded
        p = self.policy(max_requests=1)
        token = _policy.set(p)
        try:
            contexts = [copy_context(), copy_context()]
            with patch('src.http_client.requests.get', return_value=self.response(200)) as get:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    tasks = [pool.submit(ctx.run, http_get, 'https://www.cwa.gov.tw/a') for ctx in contexts]
                    outcomes = []
                    for task in tasks:
                        try: task.result(); outcomes.append('success')
                        except SourceBudgetExceeded: outcomes.append('budget')
                self.assertEqual(sorted(outcomes), ['budget', 'success'])
                self.assertEqual(get.call_count, 1)
        finally:
            _policy.reset(token)

    def test_response_body_deadline_is_checked(self):
        from src.http_client import SourceBudgetExceeded
        p = self.policy(clock=Mock(side_effect=[0, 0, 11]), max_seconds=10)
        response = requests.Response()
        response.status_code = 200
        response.raw = Mock()
        response.iter_content = lambda **kwargs: iter([b'data'])
        with self.assertRaises(SourceBudgetExceeded):
            p.get('https://example.com/a', transport=Mock(return_value=response))
