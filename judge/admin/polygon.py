from django.contrib import admin

from polygon.models import ProblemSource, ProblemSourceImport


class ProblemSourceAdmin(admin.ModelAdmin):
    pass


class ProblemSourceImportAdmin(admin.ModelAdmin):
    pass