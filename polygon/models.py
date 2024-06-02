from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from judge.models.problem import Problem
from judge.models.profile import Profile


class ProblemSource(models.Model):
    polygon_url = models.CharField(max_length=511)
    user = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='problem_sources')

    # This is DMOJ problem code to be created
    problem_code = models.CharField(
        max_length=20,
        unique=True,
        null=False,
        validators=[RegexValidator('^[a-z0-9]+$', _('Problem code must be ^[a-z0-9]+$'))],
    )
    # This is a link to actual problem, filled only after creation
    problem = models.OneToOneField(
        Problem, on_delete=models.CASCADE, null=True, blank=True, related_name='polygon_source',
    )

    created_at = models.DateTimeField(auto_now_add=True, null=False)

    class Meta:
        permissions = (('import_problems', _('Import problems from Polygon')),)


class ProblemSourceImport(models.Model):
    STATUS = (
        ('P', _('Processing')),
        ('C', _('Completed')),
        ('F', _('Failed')),
    )

    problem_source = models.ForeignKey(ProblemSource, on_delete=models.CASCADE, related_name='imports')
    status = models.CharField(max_length=2, choices=STATUS, default='P')
    log = models.TextField(null=True)
    error = models.TextField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, null=False)
    updated_at = models.DateTimeField(auto_now=True, null=False)

    class Meta:
        ordering = ['-id']
