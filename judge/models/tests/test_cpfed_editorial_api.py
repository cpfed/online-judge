import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.utils.dateparse import parse_datetime

from judge.models.tests.util import CommonDataMixin, create_problem, create_solution
from judge.views.api.api_esep import APIProblemEditorial


@override_settings(CPFED_TOKEN='test-cpfed-token')
class APIProblemEditorialTestCase(CommonDataMixin, TestCase):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def request(self, code, token='test-cpfed-token', user=None):
        headers = {'HTTP_AUTHORIZATION': 'Bearer ' + token} if token else {}
        request = RequestFactory().get('/api/esep/problem_editorial', {'code': code}, **headers)
        request.user = user or self.users['anonymous']
        with patch('judge.views.api.api_esep.timezone.now', return_value=self.now):
            return APIProblemEditorial.as_view()(request)

    def make_editorial(self, code, problem_public=True, organization_private=False, public=True, publish_on=None):
        create_problem(code, is_public=problem_public, is_organization_private=organization_private)
        return create_solution(
            code, is_public=public, content='Editorial body',
            publish_on=publish_on if publish_on is not None else self.now - timedelta(days=1),
        )

    def test_returns_published_editorial_with_existing_response_shape(self):
        solution = self.make_editorial('published')
        response = self.request('published')
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(set(payload), {'content', 'created_at'})
        self.assertEqual(payload['content'], solution.content)
        self.assertEqual(parse_datetime(payload['created_at']), solution.publish_on)

    def test_refuses_private_and_organization_private_problems_even_for_superuser(self):
        for code, options in [
            ('private', {'problem_public': False}),
            ('organization', {'organization_private': True}),
            ('privateorganization', {'problem_public': False, 'organization_private': True}),
        ]:
            with self.subTest(code=code):
                self.make_editorial(code, **options)
                # This endpoint represents the public viewer, not the service
                # account or a logged-in browser that also supplies the token.
                response = self.request(code, user=self.users['superuser'])
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('Editorial body', response.content.decode())

    def test_refuses_hidden_scheduled_and_not_yet_published_editorials(self):
        for code, options in [
            ('hidden', {'public': False}),
            ('scheduled', {'publish_on': self.now + timedelta(days=1)}),
            # Solution.is_accessible_by uses a strict publish_on < now boundary.
            ('boundary', {'publish_on': self.now}),
        ]:
            with self.subTest(code=code):
                self.make_editorial(code, **options)
                response = self.request(code)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('Editorial body', response.content.decode())

    def test_missing_editorial_and_unknown_problem_return_404(self):
        create_problem('nosolution', is_public=True)
        for code in ['nosolution', 'unknown']:
            with self.subTest(code=code):
                self.assertEqual(self.request(code).status_code, 404)

    def test_token_and_code_are_still_required(self):
        self.make_editorial('published')
        for token in ['', 'wrong-token']:
            with self.subTest(token=token):
                self.assertEqual(self.request('published', token=token).status_code, 401)
        self.assertEqual(self.request('').status_code, 400)
