import json
import unittest
from bishop_runtime.search import WebSearch
from bishop_runtime.web import WebError


class Client:
    def __init__(self, body, status=200, content_type='text/html'):
        self.response = dict(url='https://lite.duckduckgo.com/lite/', status=status, content_type=content_type, body=body.encode())
        self.calls = []
    def fetch(self, url, headers=None):
        self.calls.append((url, headers))
        return self.response


class SearchTests(unittest.TestCase):
    def test_lite_result_rows_and_redirect(self):
        client = Client('''<table><tr><td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fdocs">Example <b>Docs</b></a></td></tr><tr><td class="result-snippet">An &amp; actual source.</td></tr></table>''')
        result = WebSearch(client).search('test research', 2)
        self.assertEqual(result['results'], [dict(title='Example Docs', url='https://example.com/docs', snippet='An & actual source.')])
        self.assertEqual(result['provider'], 'duckduckgo')
        self.assertIn('retrieved_at', result)
        self.assertIn('q=test+research', client.calls[0][0])

    def test_filters_private_ad_invalid_and_bounds(self):
        urls = ['http://127.0.0.1/', 'https://10.0.0.1/', 'file:///tmp/a', 'https://localhost/', 'https://duckduckgo.com/y.js?ad=1', 'https://example.com/a', 'https://example.com/b']
        client = Client(''.join(f'<tr><td><a class="result-link" href="{url}">Title</a></td></tr><tr><td class="result-snippet">Text</td></tr>' for url in urls))
        self.assertEqual([x['url'] for x in WebSearch(client).search('a', 1)['results']], ['https://example.com/a'])

    def test_challenge_and_no_results_are_distinct(self):
        for body, status, code in [('<form id="challenge-form">', 200, 'search_challenged'), ('blocked', 202, 'search_challenged'), ('<div class="no-results">No results found</div>', 200, 'search_no_results'), ('<html>changed markup</html>', 200, 'search_invalid_response')]:
            with self.subTest(code=code), self.assertRaises(WebError) as caught:
                WebSearch(Client(body, status)).search('secretquery')
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('secretquery', str(caught.exception))

    def test_validation_before_network(self):
        client = Client('')
        for query, limit in [('', 5), ('a'*1001, 5), ('a', 0), ('a', 11), ('a', True), (None, 5)]:
            with self.assertRaises(WebError):
                WebSearch(client).search(query, limit)
        self.assertFalse(client.calls)

    def test_brave_exact_route_key_and_result_shape(self):
        client = Client(json.dumps({'web': {'results': [{'title': 'Primary', 'url': 'https://example.com/', 'description': 'Text'}]}}), content_type='application/json')
        result = WebSearch(client, 'brave', 'private-key').search('test', 2)
        self.assertEqual(client.calls, [('https://api.search.brave.com/res/v1/web/search?q=test&count=2', {'Accept': 'application/json', 'X-Subscription-Token': 'private-key'})])
        self.assertEqual(result['results'][0]['snippet'], 'Text')

    def test_ad_badges_duplicates_and_text_bounds(self):
        body = ('<tr><td><a class="result-link" href="https://advertiser.example/">Paid</a>'
                '<span class="badge--ad">Ad</span></td></tr>'
                '<tr><td><a class="result-link" href="https://example.com/">' + 'T'*400 + '</a></td></tr>'
                '<tr><td class="result-snippet">' + 'S'*2000 + '</td></tr>'
                '<tr><td><a class="result-link" href="https://example.com/">Duplicate</a></td></tr>')
        result = WebSearch(Client(body)).search('query')['results']
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['title']), 300)
        self.assertEqual(len(result[0]['snippet']), 1200)

    def test_no_automatic_brave_fallback_on_challenge(self):
        client = Client('<form id="challenge-form">', 202)
        with self.assertRaises(WebError):
            WebSearch(client, api_key='configured-but-not-selected').search('query')
        self.assertEqual(len(client.calls), 1)
        self.assertIsNone(client.calls[0][1])
        self.assertTrue(client.calls[0][0].startswith('https://lite.duckduckgo.com/'))

    def test_brave_errors_controlled(self):
        for body in ['bad json', '[]', '{"web":{"results":[1]}}']:
            with self.assertRaises(WebError):
                WebSearch(Client(body), 'brave', 'key').search('query')
        with self.assertRaises(WebError):
            WebSearch(Client(''), 'brave').search('query')
        with self.assertRaises(WebError):
            WebSearch(Client(''), 'unknown').search('query')


if __name__ == '__main__':
    unittest.main()
