import json
from operator import attrgetter

from django.http import StreamingHttpResponse
import zipfile
import io
from django.contrib.auth.models import User
from django.db.models.functions import TruncDate
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from datetime import datetime

from judge.models import (
    Language, Problem, Profile, Submission, SubmissionSource, ContestParticipation, ProblemType, ContestSubmission,
    Organization,
)
from django.db.models import F, Min, Max, Count, Prefetch, Q, Value, IntegerField

from judge.ratings import rating_class, rating_progress
from judge.views.api.api_v2 import APIListView, APIDetailView
from judge.views.submission import group_test_cases

import requests

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

def get_cpfed_token(request):
    token = None
    auth_header = request.META.get('HTTP_AUTHORIZATION')
    if auth_header and auth_header.startswith('Bearer '):
        token = auth_header.split('Bearer ')[1]
    return token


@method_decorator(csrf_exempt, name='dispatch')
class APIProblemSubmit(View):
    def post(self, request, problem_code, *args, **kwargs):
        token = get_cpfed_token(request)
        if not token or token != settings.CPFED_TOKEN:
            return JsonResponse({'error': 'Unauthorized access'}, status=401)

        source = request.POST.get('source')
        language_key = request.POST.get('language_key')
        username = request.POST.get('username')
        if not all([source, language_key, username]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        try:
            profile = Profile.objects.get(user__username=username)
        except Profile.DoesNotExist:
            return JsonResponse({'error': f'No such user {username}'}, status=404)

        try:
            problem = Problem.objects.get(code=problem_code)
        except Problem.DoesNotExist:
            return JsonResponse({'error': f'No such problem {problem_code}'}, status=404)

        try:
            language = Language.objects.get(key=language_key)
        except Language.DoesNotExist:
            return JsonResponse({'error': f'No such language {language_key}'}, status=404)

        try:
            from judge import event_poster as event
            submission = Submission.objects.create(user=profile, problem=problem, language=language)
            submission_source = SubmissionSource.objects.create(submission=submission, source=source)
            submission.judge(force_judge=True, judge_id=None)

            return JsonResponse({'submission_id': submission.id, 'last_msg': event.last()}, status=200)
        except Exception as e:
            return JsonResponse({'error': 'Internal server error occurred', 'details': str(e)}, status=500)


@method_decorator(csrf_exempt, name='dispatch')
class APISubmissionDetailEsep(View):
    def get(self, request, submission_id, *args, **kwargs):
        token = get_cpfed_token(request)
        if not token or token != settings.CPFED_TOKEN:
            return JsonResponse({'error': 'Unauthorized access'}, status=401)

        try:
            submission = Submission.objects.get(id=submission_id)
        except Submission.DoesNotExist:
            return JsonResponse({'error': f'No such submission {submission_id}'}, status=404)

        cases = []
        for batch in group_test_cases(submission.test_cases.all())[0]:
            batch_cases = [
                {
                    'type': 'case',
                    'case_id': case.case,
                    'status': case.status,
                    'time': case.time,
                    'memory': case.memory,
                    'points': case.points,
                    'total': case.total,
                } for case in batch['cases']
            ]

            # These are individual cases.
            if batch['id'] is None:
                cases.extend(batch_cases)
            # This is one batch.
            else:
                cases.append({
                    'type': 'batch',
                    'batch_id': batch['id'],
                    'cases': batch_cases,
                    'points': batch['points'],
                    'total': batch['total'],
                })

        return JsonResponse({
            'id': submission.id,
            'problem': submission.problem.code,
            'source': submission.source.source,
            'user': submission.user.user.username,
            'date': submission.date.isoformat(),
            'time': submission.time,
            'memory': submission.memory,
            'points': submission.points,
            'language': submission.language.key,
            'status': submission.status,
            'result': submission.result,
            'case_points': submission.case_points,
            'case_total': submission.case_total,
            'cases': cases,
        }, status=200)


@method_decorator(csrf_exempt, name='dispatch')
class APIUserListEsep(APIListView):
    model = Profile
    list_filters = (
        ('id', 'id'),
        ('organization', 'organizations'),
    )

    def get_paginate_by(self, queryset):
        page_size = self.request.GET.get('page_size', '10')
        try:
            page_size = int(page_size)
            return min(max(page_size, 10), 50)
        except ValueError:
            return 10

    def get_unfiltered_queryset(self):
        queryset = (
            Profile.objects
            .filter(is_unlisted=False, user__is_active=True)
            .annotate(username=F('user__username'))
            .only('id', 'points', 'performance_points', 'problem_count', 'display_rank', 'rating')
        )

        username_param = self.request.GET.get('username')
        if username_param:
            queryset = queryset.filter(user__username__istartswith=username_param)

        sort_by = self.request.GET.get('sort', '-rating')
        if sort_by == 'rating':
            queryset = queryset.order_by(F('rating').asc(nulls_last=True))
        else:
            queryset = queryset.order_by('-rating')

        return queryset

    def get_object_data(self, profile):
        return {
            'username': profile.username,
            'rating': profile.rating,
        }

    def get(self, request, *args, **kwargs):
        token = get_cpfed_token(request)
        if not token or token != settings.CPFED_TOKEN:
            return JsonResponse({'error': 'Unauthorized access'}, status=401)
        return super().get(request, *args, **kwargs)


class APIUserDetailEsep(APIDetailView):
    model = Profile
    slug_field = 'user__username'
    slug_url_kwarg = 'user'

    def get_object_data(self, profile):
        rating_value = profile.rating
        rating_rank = None

        if rating_value:
            rating_rank = Profile.objects.filter(
                is_unlisted=False, rating__gt=rating_value,
            ).count() + 1

        aggregation_data = profile.ratings.aggregate(min_rating=Min('rating'), max_rating=Max('rating'), contests=Count('contest'))
        min_rating = aggregation_data.get('min_rating')
        max_rating = aggregation_data.get('max_rating')
        contests = aggregation_data.get('contests')

        ratings = profile.ratings.order_by('-contest__end_time').select_related('contest') \
            .defer('contest__description')

        rating_data = [{
            'label': rating.contest.name,
            'rating': rating.rating,
            'ranking': rating.rank,
            'link': '%s#!%s' % (reverse('contest_ranking', args=(rating.contest.key,)), profile.user.username),
            'timestamp': (rating.contest.end_time - EPOCH).total_seconds() * 1000,
            'date': date_format(timezone.localtime(rating.contest.end_time), _('M j, Y, G:i')),
            'class': rating_class(rating.rating),
            'height': '%.3fem' % rating_progress(rating.rating),
            'score': ContestParticipation.objects.get(contest=rating.contest, user=profile, virtual=0).score
        } for rating in ratings]

        submissions = (
            profile.submission_set
            .annotate(date_only=TruncDate('date'))
            .values('date_only').annotate(cnt=Count('id'))
        )

        submission_data = {
            date_counts['date_only'].isoformat(): date_counts['cnt'] for date_counts in submissions
        }

        return {
            'id': profile.id,
            'username': profile.user.username,
            'rating': rating_value,
            'rating_rank': rating_rank,
            'min_rating': min_rating,
            'max_rating': max_rating,
            'contests': contests,
            'problem_count': profile.problem_count,
            'rating_data': rating_data,
            'submission_data': submission_data
        }


class APIProblemListEsep(APIListView):
    model = Problem
    basic_filters = (
        ('partial', 'partial'),
    )
    list_filters = (
        ('type', 'types__full_name'),
    )

    def get_unfiltered_queryset(self):
        return (
            Problem.get_visible_problems(self.request.user)
            .select_related('group')
            .prefetch_related(
                Prefetch(
                    'types',
                    queryset=ProblemType.objects.only('full_name'),
                    to_attr='type_list',
                ),
            )
            .order_by('id')
            .distinct()
        )

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if settings.ENABLE_FTS and 'search' in self.request.GET:
            query = ' '.join(self.request.GET.getlist('search')).strip()
            if query:
                queryset = queryset.search(query)
        return queryset

    def get_object_data(self, problem):
        username = self.kwargs.get('username')

        data = {
            'code': problem.code,
            'name': problem.name,
            'types': list(map(attrgetter('full_name'), problem.type_list)),
            'group': problem.group.full_name,
            'ac_rate': problem.ac_rate,
            'is_organization_private': problem.is_organization_private,
            'is_public': problem.is_public,
        }
        if username:
            try:
                profile = Profile.objects.get(user__username=username)
                is_solved = Submission.objects.filter(user=profile, problem=problem, result='AC', case_points__gte=F('case_total')).exists()
                if is_solved:
                    data.update({
                        'user_status': 'AC'
                    })
                else:
                    submissions = Submission.objects.filter(user=profile, problem=problem).order_by('-judged_date')
                    if submissions.exists():
                        last_submission = submissions.first()
                        data.update({
                            'user_status': last_submission.result
                        })
                    else:
                        data.update({
                            'user_status': 'N'
                        })
            except Exception as e:
                pass

        return data


@method_decorator(csrf_exempt, name='dispatch')
class APIProblemTypeProgress(APIListView):
    def get(self, request, *args, **kwargs):
        token = get_cpfed_token(request)
        if not token or token != settings.CPFED_TOKEN:
            return JsonResponse({'error': 'Unauthorized access'}, status=401)

        full_names_param = request.query_params.get('full_names', '')
        full_names = [name.strip() for name in full_names_param.split(',') if name.strip()]

        if not isinstance(full_names, list):
            return JsonResponse({'error': 'full_names must be a list'}, status=400)

        if not full_names:
            return JsonResponse({'error': 'full_names list cannot be empty'}, status=400)

        username = request.GET.get('username')
        if not username:
            return JsonResponse({'error': 'Missing username'}, status=400)

        try:
            profile = Profile.objects.get(user__username=username)
        except Profile.DoesNotExist:
            return JsonResponse({'error': f'No such user {username}'}, status=404)


class APIProblemTypeProgressList(APIListView):
    model = ProblemType

    list_filters = (
        ('type', 'full_name'),
    )

    def get_unfiltered_queryset(self):
        queryset = ProblemType.objects.all()

        username = self.kwargs.get('username')

        if username:
            try:
                profile = Profile.objects.get(user__username=username)
            except Profile.DoesNotExist:
                return ProblemType.objects.none()
        else:
            profile = None

        if profile:
            queryset = queryset.annotate(
                total_problems=Count('problem', distinct=True)
            )

            queryset = queryset.annotate(
                solved_problems=Count(
                    'problem',
                    filter=Q(
                        problem__submission__user=profile,
                        problem__submission__result='AC',
                        problem__submission__case_points__gte=F('problem__submission__case_total')
                    ),
                    distinct=True
                )
            )
        else:
            queryset = queryset.annotate(
                total_problems=Count('problem', distinct=True),
                solved_problems=Value(0, output_field=IntegerField())
            )

        return queryset

    def get_object_data(self, problem_type):
        data = {
            'full_name': problem_type.full_name,
            'total_problems': problem_type.total_problems,
        }

        if hasattr(problem_type, 'solved_problems'):
            data['solved_problems'] = problem_type.solved_problems
            data['total_problems'] = problem_type.total_problems

        return data


class APIDownloadContestSubmissons(View):
    def get(self, request):
        token = get_cpfed_token(request)
        if not token or token != settings.CPFED_TOKEN:
            return JsonResponse({'error': 'Unauthorized access'}, status=401)

        contest_key = request.GET.get('contest_key')
        if not contest_key:
            return JsonResponse({'error': 'contest_key must be provided'}, status=400)

        contest_submissions = ContestSubmission.objects.filter(
            participation__contest__key=contest_key,
            participation__virtual=0
        ).select_related(
            'submission__user__user',
            'submission__source',
            'submission__problem',
            'submission__language',
        ).values(
            'submission__user__user__username',
            'submission__language__extension',
            'submission__source__source',
            'submission__problem__code',
            'submission__id',
            'submission__result'
        ).iterator(chunk_size=100)

        def generate_zip():
            buffer = io.BytesIO()

            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for contest_submission in contest_submissions:
                    username = contest_submission['submission__user__user__username']
                    extension = contest_submission['submission__language__extension']
                    problem_code = contest_submission['submission__problem__code']
                    source_code = contest_submission['submission__source__source']
                    submission_id = contest_submission['submission__id']
                    submission_result = contest_submission['submission__result']
                    filename = f"{username}-{problem_code}-{submission_id}-{submission_result}.{extension}"

                    zip_file.writestr(filename, source_code.encode('utf-8'))

            buffer.seek(0)
            yield buffer.read()

        response = StreamingHttpResponse(
            generate_zip(),
            content_type='application/zip'
        )
        response['Content-Disposition'] = f'attachment; filename={contest_key}_submissions.zip'

        return response


@method_decorator(csrf_exempt, name='dispatch')
class APISyncUsersWithEsep(View):
    def post(self, request, *args, **kwargs):
        try:
            token = get_cpfed_token(request)
            if not token or token != settings.CPFED_TOKEN:
                return JsonResponse({'error': 'Unauthorized access'}, status=401)

            data = json.loads(request.body)

            org_id = data.get('org_id')
            emails = data.get('emails')
            usernames = data.get('usernames')

            if not all([org_id, emails, usernames]):
                return JsonResponse(
                    {'detail': 'Missing required parameters.'}, status=400,
                )
            if len(usernames) != len(emails):
                return JsonResponse(
                    {'detail': 'Usernames and emails length is not same.'}, status=400,
                )

            org = get_object_or_404(Organization, id=int(org_id))
            for user_email, username in zip(emails, usernames):
                user, created = User.objects.get_or_create(email=user_email, username=username)
                if created:
                    profile, _ = Profile.objects.get_or_create(user=user, defaults={
                        'language': Language.objects.get(key=settings.DEFAULT_USER_LANGUAGE),
                        'is_banned_from_problem_voting': True
                    })
                    profile.organizations.add(org)

            return JsonResponse({'detail': 'Users added to org successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'detail': str(e)}, status=400)


def attach_proctoring_token(user, contest):
    response = requests.post(
        'https://api.trustexam.ai/api/external-session/assignment.json',
        params={
            'api_token': settings.TRUSTEXAM_API_KEY
        },
        headers={
            'Content-Type': 'application/json'
        },
        json={
            "assignment": {
                "external_id": contest.key,
                "name": contest.name,
                "external_url": "https://esep.cpfed.kz",
                "settings": {
                    "proctoring_settings": {
                      "check_env": True,
                      "browser_type": "*",
                      "object_detect": False,
                      "displays_check": False,
                      "focus_detector": False,
                      "noise_detector": False,
                      "read_clipboard": 0,
                      "content_protect": False,
                      "face_landmarker": False,
                      "fullscreen_mode": False,
                      "id_verification": False,
                      "speech_detector": False,
                      "main_camera_record": False,
                      "main_camera_upload": False,
                      "photo_head_identity": 0,
                      "screen_share_record": True,
                      "screen_share_upload": False,
                      "video_head_identity": False,
                      "head_tracking_client": 0,
                      "second_camera_record": False,
                      "second_camera_upload": False,

                      "main_camera_blackhole": False,
                      "screen_share_blackhole": False,
                      "second_camera_blackhole": False,

                      "second_microphone_record": False,
                      "second_microphone_upload": False,

                      "second_microphone_blackhole": False,
                      "head_tracking_server_realtime": False,
                      "head_compare_euclidean_distance": 0.5
                    }
                }
            },
            "student": {
                "external_id": str(user.id),
                "name": user.username,
                "firstname": user.username
            }
        }
    )

    if response.status_code == 200:
        res = response.json()
        access_token = res['external_session']['token']
        token_key = f'proctoring:session:{user.id}:{contest.id}'
        cache_timeout = contest.contest_window_length.seconds
        cache.set(token_key, access_token, timeout=cache_timeout)
        return JsonResponse({'token': res['access_token']}, status=200)
    else:
        return JsonResponse({'error': 'Failed to initialize proctoring'}, status=500)