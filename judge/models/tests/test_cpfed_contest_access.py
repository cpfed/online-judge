import json

from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from judge.models import Contest, Language, Submission
from judge.models.tests.util import (
    CommonDataMixin, create_contest, create_contest_participation, create_contest_problem,
    create_problem, create_user,
)
from judge.views.api.api_esep import (
    APIContestProblemDetail, APIContestProblems, APIContestUserProblemSubmissions, APIStandings,
)


@override_settings(CPFED_TOKEN='test-cpfed-contest-token')
class CPFEDContestAccessTestCase(CommonDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.member = create_user('contest-member')
        cls.member.profile.organizations.add(cls.organizations['open'])
        cls.curator = create_user('contest-curator')
        cls.target = create_user('contest-target')
        cls.problem = create_problem('access-task', description='Restricted statement')

    def make_contest(self, **kwargs):
        now = timezone.now()
        fields = {
            'is_visible': True,
            'start_time': now - timezone.timedelta(hours=1),
            'end_time': now + timezone.timedelta(hours=1),
            'curators': [self.curator.username],
        }
        fields.update(kwargs)
        contest = create_contest('access-round', **fields)
        create_contest_problem(contest=contest, problem=self.problem)
        create_contest_participation(contest=contest, user=self.target.profile)
        Submission.objects.create(
            user=self.target.profile, problem=self.problem, contest_object=contest,
            language=Language.objects.first(), status='D', result='AC', points=100,
            case_points=100, case_total=100,
        )
        return contest

    def request(self, view, contest, viewer=None, token='test-cpfed-contest-token'):
        data = {'contest_key': contest.key}
        if view is APIContestUserProblemSubmissions:
            data.update(username=self.target.username, problem_code=self.problem.code)
            if viewer:
                data['viewer'] = viewer.username
        elif viewer:
            data['username'] = viewer.username
        request = RequestFactory().get('/', data, HTTP_AUTHORIZATION=f'Bearer {token}')
        kwargs = {}
        if view in (APIContestProblems, APIContestProblemDetail):
            kwargs['contest_key'] = contest.key
        if view is APIContestProblemDetail:
            kwargs['problem_code'] = self.problem.code
        return view.as_view()(request, **kwargs)

    def assert_denied(self, contest, viewer=None, status=404):
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblems, APIContestProblemDetail):
            with self.subTest(view=view.__name__, viewer=viewer):
                response = self.request(view, contest, viewer)
                self.assertEqual(response.status_code, status)
                self.assertNotIn('Restricted statement', response.content.decode())

    def test_private_contest_requires_allowlisted_viewer_even_after_end(self):
        contest = self.make_contest(
            is_private=True, private_contestants=[self.member.username],
            end_time=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assert_denied(contest)
        self.assert_denied(contest, self.users['normal'])
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, self.member).status_code, 200)

    def test_hidden_contest_rejects_anonymous_and_ordinary_viewers(self):
        contest = self.make_contest(is_visible=False, end_time=timezone.now() - timezone.timedelta(minutes=1))
        self.assert_denied(contest)
        self.assert_denied(contest, self.users['normal'])

    def test_organization_contest_requires_membership_for_scoreboard_and_submissions(self):
        contest = self.make_contest(is_organization_private=True, organizations=['open'])
        self.assert_denied(contest)
        self.assert_denied(contest, self.users['normal'])
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, self.member).status_code, 200)

    def test_combined_private_and_organization_contest_requires_both(self):
        contest = self.make_contest(
            is_private=True, is_organization_private=True, organizations=['open'],
            private_contestants=[self.target.username],
        )
        self.assert_denied(contest, self.member)
        self.assert_denied(contest, self.target)

    def test_scoreboard_only_grant_does_not_grant_organization_statements(self):
        viewer = self.users['normal']
        contest = self.make_contest(
            is_organization_private=True, organizations=['open'],
            view_contest_scoreboard=[viewer.username],
        )
        self.assertEqual(self.request(APIStandings, contest, viewer).status_code, 200)
        for view in (APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, viewer).status_code, 403)

    def test_curator_can_preview_hidden_future_contest(self):
        contest = self.make_contest(
            is_visible=False, start_time=timezone.now() + timezone.timedelta(minutes=30),
        )
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, self.curator).status_code, 200)

    def test_organization_member_cannot_preview_future_statements(self):
        contest = self.make_contest(
            is_organization_private=True, organizations=['open'],
            start_time=timezone.now() + timezone.timedelta(minutes=30),
        )
        # Even an existing registration must not reveal tasks before the start.
        create_contest_participation(contest=contest, user=self.member.profile)
        for view in (APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, self.member).status_code, 403)

    def test_public_live_statement_requires_participation(self):
        contest = self.make_contest()
        for view in (APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest).status_code, 403)
            self.assertEqual(self.request(view, contest, self.users['normal']).status_code, 403)
            self.assertEqual(self.request(view, contest, self.target).status_code, 200)

    def test_public_archive_remains_anonymously_accessible(self):
        contest = self.make_contest(end_time=timezone.now() - timezone.timedelta(minutes=1))
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest).status_code, 200)

    def test_hidden_scoreboard_still_limits_results_to_their_owner(self):
        contest = self.make_contest(scoreboard_visibility=Contest.SCOREBOARD_HIDDEN)
        response = self.request(APIStandings, contest)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(self.problem.code, response.content.decode())
        self.assertEqual(self.request(APIStandings, contest, self.users['normal']).status_code, 404)
        self.assertEqual(self.request(APIContestUserProblemSubmissions, contest).status_code, 403)
        self.assertEqual(self.request(APIContestUserProblemSubmissions, contest, self.target).status_code, 200)
        self.target.profile.current_contest = contest.users.get(user=self.target.profile)
        self.target.profile.save(update_fields=['current_contest'])
        own = self.request(APIStandings, contest, self.target)
        self.assertEqual(own.status_code, 200)
        self.assertEqual([row['username'] for row in json.loads(own.content)['rows']], [self.target.username])

    def test_future_public_scoreboard_does_not_reveal_problem_metadata(self):
        contest = self.make_contest(start_time=timezone.now() + timezone.timedelta(minutes=30))
        for viewer in (None, self.users['normal'], self.target):
            response = self.request(APIStandings, contest, viewer)
            self.assertEqual(response.status_code, 404)
            self.assertNotIn(self.problem.code, response.content.decode())
            self.assertNotIn(self.problem.name, response.content.decode())

    def test_frozen_results_stay_hidden_from_other_viewers(self):
        contest = self.make_contest(freeze_time=timezone.timedelta(minutes=30))
        response = self.request(APIContestUserProblemSubmissions, contest)
        row = json.loads(response.content)['submissions'][0]
        self.assertTrue(row['frozen'])
        self.assertIsNone(row['result'])
        self.assertIsNone(row['points'])
        own = self.request(APIContestUserProblemSubmissions, contest, self.target)
        self.assertEqual(json.loads(own.content)['submissions'][0]['result'], 'AC')
        curator = self.request(APIContestUserProblemSubmissions, contest, self.curator)
        self.assertEqual(json.loads(curator.content)['submissions'][0]['result'], 'AC')

    def test_service_token_is_still_required(self):
        contest = self.make_contest(end_time=timezone.now() - timezone.timedelta(minutes=1))
        for view in (APIStandings, APIContestUserProblemSubmissions, APIContestProblems, APIContestProblemDetail):
            self.assertEqual(self.request(view, contest, token='invalid').status_code, 401)
