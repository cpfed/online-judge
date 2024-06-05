import re

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, FormView
from django.views.generic.edit import FormMixin

from judge.models import Problem
from . import api
from .forms import ImportForm, ReimportForm
from .models import ProblemSource
from .problem import ProblemImportError
from .tasks import import_problem as import_problem_task


class ImportProblemView(PermissionRequiredMixin, FormView):
    form_class = ImportForm
    template_name = 'polygon/import_problem.html'
    permission_required = 'polygon.import_problems'

    def form_valid(self, form):
        with transaction.atomic():
            # Ensure changes are committed
            problem_source = ProblemSource(
                polygon_id=form.cleaned_data['polygon_id'],
                author=self.request.profile,
                problem_code=form.cleaned_data['code'],
            )
            problem_source.save()

        task = import_problem_task.delay(problem_source.id, self.request.profile.id)

        return HttpResponseRedirect(
            reverse('task_status', kwargs={'task_id': task.id}) +
            '?always=1&redirect=' +
            reverse('polygon_source', kwargs={'pk': problem_source.id}),
        )

    def get_context_data(self, **kwargs):
        kwargs['polygon_user'] = settings.POLYGON_USER
        return super().get_context_data(**kwargs)


class ProblemSourceView(PermissionRequiredMixin, FormMixin, DetailView):
    form_class = ReimportForm
    model = ProblemSource
    permission_required = 'polygon.import_problems'

    def get_object(self, queryset=None):
        result: ProblemSource = super().get_object(queryset)

        if result.problem is None and result.author != self.request.profile:
            raise PermissionDenied()

        if result.problem is not None and not result.problem.is_editable_by(self.request.user):
            raise PermissionDenied()

        return result

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def form_valid(self, form):
        problem_source = self.get_object()

        task = import_problem_task.delay(problem_source.id, self.request.profile.id)

        return HttpResponseRedirect(
            reverse('task_status', kwargs={'task_id': task.id}) +
            '?always=1&redirect=' +
            reverse('polygon_source', kwargs={'pk': problem_source.id}),
        )


@require_POST
@csrf_exempt
@permission_required('polygon.import_problems')
def check_problem(request):
    if 'id' not in request.POST or not (problem_id := request.POST['id']).isdigit():
        return HttpResponseBadRequest('Bad ID')

    problem_id = int(problem_id)

    try:
        problem = api.get_problem(problem_id)
    except ProblemImportError as exc:
        return HttpResponseBadRequest(str(exc))

    code = re.sub(r'[^a-z0-9]+', '', problem.name.lower())

    def append_number_to_code(code: str, idx: int) -> str:
        """To make an unique code, we try to add some numbers at the end.

        Code should be not longer than 20 characters, so we cut it if needed."""

        if idx == 1:
            return code
        else:
            code = code[:20 - len(str(idx))]
            return f'{code}{idx}'

    idx = 1
    while True:
        suggested_code = append_number_to_code(code, idx)

        if not Problem.objects.filter(code=suggested_code).exists():
            return JsonResponse({'suggested_code': suggested_code})

        idx += 1

        if idx == 100:
            return JsonResponse({'suggested_code': None})


@require_POST
@csrf_exempt
@permission_required('polygon.import_problems')
def check_code_uniqueness(request):
    if 'code' not in request.POST:
        return HttpResponseBadRequest('Bad code')

    code = request.POST['code']

    try:
        Problem._meta.get_field('code').run_validators(code)
    except ValidationError as exc:
        return HttpResponseBadRequest(exc.error_list[0])

    if Problem.objects.filter(code=code).exists():
        return HttpResponseBadRequest(_('Problem exists'))

    return HttpResponse()
