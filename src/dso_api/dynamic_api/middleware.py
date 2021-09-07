import json
import logging

from django.utils.deprecation import MiddlewareMixin
from schematools.contrib.django.models import Profile
from schematools.permissions import UserScopes

audit_log = logging.getLogger("dso_api.audit")


class DatasetMiddleware(MiddlewareMixin):
    """
    Assign `dataset` to request, for easy access.
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        # Load the profiles once on startup of the application (just like datasets are read once).
        self.all_profiles = [p.schema for p in Profile.objects.all()]

    def process_request(self, request):
        """
        This method installs the `user_scopes` for the OAS views.
        """

        # get_token_scopes should be set by authorization_django. We use it,
        # instead of is_authorized_for, to get more control over authorization
        # checks and to enable more precise logging.

        if request.method == "OPTIONS":
            # OPTIONS requests have no get_token_scopes, but don't need a UserScopes either.
            return

        # get_token_scopes is a data attribute, not a method.
        scopes = request.get_token_scopes
        request.user_scopes = UserScopes(request.GET, scopes, self.all_profiles)

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Make current dataset available across whole application.
        """
        if not hasattr(request, "dataset"):
            try:
                request.dataset = view_func.cls.model._dataset_schema
            except AttributeError:
                pass

        return None


class TemporalTableMiddleware(MiddlewareMixin):
    """
    Assign `versioned`, `table_version` and `temporal_slice` to request.
    """

    def process_request(self, request):
        request.versioned = False
        request.table_version = None
        request.table_temporal_slice = None

    def process_view(self, request, view_func, view_args, view_kwargs):
        try:
            if not view_func.cls.model.is_temporal():
                return None
        except AttributeError:
            return None

        request.versioned = True
        table = view_func.cls.model.table_schema()
        if version := request.GET.get(table.temporal.identifier):
            request.table_version = version

        for key, fields in table.temporal.dimensions.items():
            if request.GET.get(key):
                request.table_temporal_slice = dict(
                    key=key, value=request.GET.get(key), fields=fields
                )

        return None


class RequestAuditLoggingMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        data = None
        try:
            data = json.loads(request.body)
            if data is None:
                raise ValueError
        except ValueError:
            if request.method == "GET":
                data = request.GET
            else:
                data = request.POST
        except Exception as e:
            print(e)

        subject = None
        if hasattr(request, "get_token_subject"):
            subject = request.get_token_subject

        log = dict(
            path=request.path,
            method=request.method,
            request_headers=repr(request.META),
            subject=subject,
            data=data,
        )

        audit_log.debug(json.dumps(log))
