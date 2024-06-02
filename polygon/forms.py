from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

__all__ = ('ImportForm', 'ReimportForm')


class ImportForm(forms.Form):
    url = forms.CharField(
        label=_('Polygon URL'),
        validators=[
            RegexValidator('^https://polygon.codeforces.com/', _('Only polygon.codeforces.com links are supported')),
        ],
        max_length=511,
        help_text=_('Problem URL in the right sidebar'),
    )

    code = forms.CharField(
        label=_('Problem code'),
        max_length=20,
        validators=[RegexValidator('^[a-z0-9]+$', _('Problem code must be ^[a-z0-9]+$'))],
        help_text=_('A short, unique code for the problem, used in the URL after /problem/'),
    )


class ReimportForm(forms.Form):
    ...
