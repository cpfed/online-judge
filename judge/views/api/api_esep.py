from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from judge.models import (
    Language, Problem, Profile, Submission, SubmissionSource,
)
from judge.views.submission import group_test_cases


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
