import json
import string

from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.crypto import get_random_string

from judge.models import Language, Organization, Profile


def register_user(username, password, full_name, org_id):
    """
    Register a new user with the given details and add them to the specified organization.
    """

    org = get_object_or_404(Organization, id=org_id)

    with transaction.atomic():
        user = _create_user(username, password)
        _create_profile_for_user(user, full_name, org)


def _create_user(username, password):
    user = User(
        username=username,
        email=f'{username}@esep.cpfed.kz',
        is_active=True,
        is_superuser=False,
        is_staff=False,
    )
    user.set_password(password)

    try:
        user.save()
    except IntegrityError:
        raise ValueError(f'User with username {username} already exists.')

    return user


def _create_profile_for_user(user, full_name, org):
    profile = Profile(
        user=user,
        language=Language.objects.get(key=settings.DEFAULT_USER_LANGUAGE),
        username_display_override=full_name,
        mute=True,
        is_banned_from_problem_voting=True,
    )

    try:
        profile.save()
        profile.organizations.add(org)
    except IntegrityError:
        raise ValueError(f'Error creating profile for user {user.username}.')


@method_decorator(csrf_exempt, name='dispatch')
class SyncUsersFromCPFEDView(View):
    def post(self, request, token, *args, **kwargs):
        try:
            if token != settings.CPFED_TOKEN:
                return JsonResponse({'detail': 'Unauthorized'}, status=403)

            data = json.loads(request.body)

            username = data.get('username')
            password = data.get('password')
            full_name = data.get('full_name')
            org_id = data.get('org_id')

            if not all([username, password, full_name, org_id]):
                return JsonResponse(
                    {'detail': 'Missing required parameters.'}, status=400,
                )

            register_user(username, password, full_name, org_id)

            return JsonResponse({'detail': 'User registered successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'detail': str(e)}, status=400)


def add_org(username, org_id):
    """
    Add org to the given user
    """

    user = org = get_object_or_404(User, username=username)
    org = get_object_or_404(Organization, id=org_id)
    profile = user.profile
    profile.organizations.add(org)


@method_decorator(csrf_exempt, name='dispatch')
class SyncRegionFromCPFEDView(View):
    def post(self, request, token, *args, **kwargs):
        try:
            if token != settings.CPFED_TOKEN:
                return JsonResponse({'detail': 'Unauthorized'}, status=403)

            data = json.loads(request.body)

            username = data.get('username')
            org_id = data.get('org_id')

            if not all([username, org_id]):
                return JsonResponse(
                    {'detail': 'Missing required parameters.'}, status=400,
                )

            add_org(username, org_id)

            return JsonResponse({'detail': 'Region added successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'detail': str(e)}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class AddUsersToOrgCPFEDView(View):
    def post(self, request, token, *args, **kwargs):
        try:
            if token != settings.CPFED_TOKEN:
                return JsonResponse({'detail': 'Unauthorized'}, status=403)

            data = json.loads(request.body)

            org_id = data.get('org_id')
            emails = data.get('emails')

            if not all([org_id, emails]):
                return JsonResponse(
                    {'detail': 'Missing required parameters.'}, status=400,
                )

            org = get_object_or_404(Organization, id=int(org_id))
            for user_email in emails:
                users = User.objects.filter(email=user_email)
                while len(users) == 0:
                    username = 'tmp_username_' + get_random_string(15, allowed_chars=string.ascii_lowercase)
                    print(username)
                    user, created = User.objects.get_or_create(username=username, defaults={'email': user_email})
                    if created:
                        users = [user]
                for user in users:
                    profile, _ = Profile.objects.get_or_create(user=user, defaults={
                        'language': Language.objects.get(key=settings.DEFAULT_USER_LANGUAGE),
                        'is_banned_from_problem_voting': True
                    })
                    profile.organizations.add(org)

            return JsonResponse({'detail': 'Users added to org successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'detail': str(e)}, status=400)
