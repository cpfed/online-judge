import json
from operator import attrgetter

from django.db.models.functions import TruncDate
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from datetime import datetime

from judge.models import (
    Language, Problem, Profile, Submission, SubmissionSource, ContestParticipation, ProblemType,
)
from django.db.models import F, Min, Max, Count, Prefetch

from judge.ratings import rating_class, rating_progress
from judge.views.api.api_v2 import APIListView, APIDetailView
from judge.views.submission import group_test_cases

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
            submission = Submission.objects.create(user=profile, problem=problem, language=language)
            submission_source = SubmissionSource.objects.create(submission=submission, source=source)
            submission.judge(force_judge=True, judge_id=None)

            return JsonResponse({'submission_id': submission.id}, status=200)
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
        ('username', 'username'),
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
        return (
            Profile.objects
            .filter(is_unlisted=False, user__is_active=True)
            .annotate(username=F('user__username'))
            .order_by('-rating')
            .only('id', 'points', 'performance_points', 'problem_count', 'display_rank', 'rating')
        )

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
