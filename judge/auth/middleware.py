import base64

from django.contrib import auth
from django.core.exceptions import ImproperlyConfigured
from django.utils.deprecation import MiddlewareMixin
import jwt
from judge.models import Profile, Language
from django.contrib.auth.models import User
from django.conf import settings


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



class JWTAuthMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # AuthenticationMiddleware is required so that request.user exists.
        if not hasattr(request, 'user'):
            raise ImproperlyConfigured(
                'The Django remote user auth middleware requires the'
                ' authentication middleware to be installed.  Edit your'
                ' MIDDLEWARE setting to insert'
                " 'django.contrib.auth.middleware.AuthenticationMiddleware'"
                ' before the RemoteUserMiddleware class.')
        
        # We don't want to use JWT auth when the secret is not set
        if settings.JWT_SECRET == '':
            return

        user = None
        
        try:
            token = request.COOKIES.get('cpfed_auth')
            if not token:
                return

            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=['HS256'])

            username = payload.get("username") 
            email = payload.get("email")

            if username and email:

                user, created = User.objects.get_or_create(email=email, defaults={"username": username}, is_active=True)
                if created:
                    if user.username != username:
                        user.username = username
                    
                    user.set_unusable_password()
                    user.save()

                    profile = Profile(user=user)
                    profile.language = Language.objects.get(key=settings.DEFAULT_USER_LANGUAGE)
                    profile.save()
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            return
        except (KeyError, UnicodeDecodeError, ValueError):
            return

        if request.user.is_authenticated:
            if request.user.get_username() == self.clean_username(username, request):
                return
            else:
                self._remove_invalid_user(request)

    
        if user:
             # Assign the specific backend to the user
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            
            request.user = user
            auth.login(request, user)

    def process_response(self, request, response):
        if 'cpfed_auth' in request.COOKIES:
            response.delete_cookie('cpfed_auth')
        return response
        
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