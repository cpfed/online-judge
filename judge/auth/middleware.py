import base64

from django.contrib import auth
from django.core.exceptions import ImproperlyConfigured
from django.utils.deprecation import MiddlewareMixin


class BasicAuthMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # AuthenticationMiddleware is required so that request.user exists.
        if not hasattr(request, 'user'):
            raise ImproperlyConfigured(
                'The Django remote user auth middleware requires the'
                ' authentication middleware to be installed.  Edit your'
                ' MIDDLEWARE setting to insert'
                " 'django.contrib.auth.middleware.AuthenticationMiddleware'"
                ' before the RemoteUserMiddleware class.')
        try:
            header = request.headers['Authorization']
            if not header.startswith('Basic '):
                return
            username, password = base64.b64decode(header[6:]).decode().split(':')
        except (KeyError, UnicodeDecodeError, ValueError):
            return

        if request.user.is_authenticated:
            if request.user.get_username() == self.clean_username(username, request):
                return
            else:
                self._remove_invalid_user(request)

        user = auth.authenticate(request, username=username, password=password)
        if user:
            request.user = user
            auth.login(request, user)

    def clean_username(self, username, request):
        backend_str = request.session[auth.BACKEND_SESSION_KEY]
        backend = auth.load_backend(backend_str)
        try:
            username = backend.clean_username(username)
        except AttributeError:
            pass
        return username

    def _remove_invalid_user(self, request):
        auth.logout(request)
