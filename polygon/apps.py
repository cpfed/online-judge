from django.apps import AppConfig


class PolygonConfig(AppConfig):
    name = 'polygon'

    def ready(self):
        import shutil

        from .problem.statement import pandoc_get_version

        if not shutil.which('pandoc'):
            raise RuntimeError('pandoc not installed')
        if pandoc_get_version() < (3, 0, 0):
            raise RuntimeError('pandoc version must be at least 3.0.0')
