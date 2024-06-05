from django.conf import settings
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import DetailView, FormView
from django.views.generic.edit import FormMixin

from .forms import ImportForm, ReimportForm
from .models import ProblemSource
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
