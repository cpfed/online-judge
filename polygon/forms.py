from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

__all__ = ('ImportForm', 'ReimportForm')


class ImportForm(forms.Form):
    polygon_id = forms.IntegerField(
        label=_('Polygon problem ID'),
        required=True,
        help_text=_('Numeric problem ID from Polygon'),
    )

    code = forms.CharField(
        label=_('Problem code'),
        max_length=20,
        validators=[RegexValidator('^[a-z0-9]+$', _('Problem code must be ^[a-z0-9]+$'))],
        help_text=_('A short, unique code for the problem, used in the URL after /problem/'),
    )


class ReimportForm(forms.Form):
    ...
