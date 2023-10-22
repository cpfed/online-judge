from django.conf import settings
from django.contrib.auth.models import User
from judge.models import Language, Profile, Organization
from django.shortcuts import get_object_or_404
from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
import json


def register_user(username, password, full_name, org_id):
    """
    Register a new user with the given details and add them to the specified organization.
    """

    org = get_object_or_404(Organization, id=org_id)

    with transaction.atomic():
        user = _create_user(username, password)
        _create_profile_for_user(user, full_name, org)


def _create_user(username, password):
    """Creates and returns a new user."""
    user = User(
        username=username,
        email=f"{username}@esep.cpfed.kz",
        is_active=True,
        is_superuser=False,
        is_staff=False,
    )
    user.set_password(password)

    try:
        user.save()
    except IntegrityError:
        raise ValueError(f"User with username {username} already exists.")

    return user


def _create_profile_for_user(user, full_name, org):
    """Creates a profile for the given user and associates it with the specified organization."""
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
        raise ValueError(f"Error creating profile for user {user.username}.")


@method_decorator(csrf_exempt, name="dispatch")
class SyncUsersFromCPFEDView(View):
    def post(self, request, token, *args, **kwargs):
        try:
            if token != settings.CPFED_TOKEN:
                return JsonResponse({"detail": "Unauthorized"}, status=403)

            data = json.loads(request.body)

            username = data.get("username")
            password = data.get("password")
            full_name = data.get("full_name")
            org_id = data.get("org_id")

            if not all([username, password, full_name, org_id]):
                return JsonResponse(
                    {"detail": "Missing required parameters."}, status=400
                )

            register_user(username, password, full_name, org_id)

            return JsonResponse({"detail": "User registered successfully"}, status=201)
        except Exception as e:
            return JsonResponse({"detail": str(e)}, status=400)
