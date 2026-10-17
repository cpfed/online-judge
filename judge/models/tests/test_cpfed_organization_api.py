import json

from django.test import RequestFactory, TestCase, override_settings

from judge.models.tests.util import CommonDataMixin, create_organization, create_user
from judge.views.api.api import RemoveUsersFromOrgCPFEDView


@override_settings(CPFED_TOKEN='test-cpfed-token')
class RemoveUsersFromOrgCPFEDViewTestCase(CommonDataMixin, TestCase):
    @classmethod
    def setUpTestData(self):
        super().setUpTestData()
        self.other_organization = create_organization(name='other')
        self.removed_user = create_user(username='removed-user', email='removed@example.com')
        self.kept_user = create_user(username='kept-user', email='kept@example.com')
        self.removed_user.profile.organizations.add(self.organizations['open'], self.other_organization)
        self.kept_user.profile.organizations.add(self.organizations['open'])

    def request(self, token='test-cpfed-token', data=None):
        request = RequestFactory().post(
            '/api/remove-users-from-org/',
            data=json.dumps(data or {
                'org_id': self.organizations['open'].id,
                'emails': ['REMOVED@example.com', 'missing@example.com'],
            }),
            content_type='application/json',
        )
        return RemoveUsersFromOrgCPFEDView.as_view()(request, token=token)

    def test_removes_matching_members_only_from_requested_organization(self):
        response = self.request()
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['requested'], 2)
        self.assertEqual(payload['removed'], 1)
        self.assertNotIn(self.removed_user.profile, self.organizations['open'])
        self.assertIn(self.kept_user.profile, self.organizations['open'])
        self.assertIn(self.removed_user.profile, self.other_organization)

    def test_rejects_invalid_token_without_changing_membership(self):
        response = self.request(token='wrong-token')

        self.assertEqual(response.status_code, 403)
        self.assertIn(self.removed_user.profile, self.organizations['open'])

    def test_rejects_non_list_emails(self):
        response = self.request(data={
            'org_id': self.organizations['open'].id,
            'emails': 'removed@example.com',
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn(self.removed_user.profile, self.organizations['open'])
