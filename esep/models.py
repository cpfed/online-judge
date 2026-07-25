from django.db import models
from django.db.models import CASCADE
from django.utils.translation import gettext_lazy as _

from judge.models import Contest, Profile

# ESEP-специфичные модели держим в отдельном приложении, чтобы миграции не конфликтовали
# с апстримом DMOJ (приложение judge) при синхронизации форка. FK на judge.* — кросс-апповые,
# обратные аксессоры (contest.announcements) работают как обычно.


class ContestAnnouncement(models.Model):
    contest = models.ForeignKey(Contest, verbose_name=_('contest'), related_name='announcements', on_delete=CASCADE)
    author = models.ForeignKey(Profile, verbose_name=_('author'), related_name='contest_announcements', on_delete=CASCADE)
    body = models.TextField(verbose_name=_('announcement body'))
    time = models.DateTimeField(verbose_name=_('announcement time'), auto_now_add=True)

    class Meta:
        ordering = ['-time']
        verbose_name = _('contest announcement')
        verbose_name_plural = _('contest announcements')
