import django_healthchecks.urls
from django.conf import settings
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular import openapi
from rest_framework import exceptions, permissions, renderers
from rest_framework.schemas import get_schema_view

import dso_api.datasets.urls
import dso_api.dynamic_api.urls


class ExtendedSchemaGenerator(openapi.SchemaGenerator):
    """drf_spectacular also provides 'components' which DRF doesn't do."""

    extra_schema = {
        "info": {
            "title": "DSO-API",
            "version": "v1",
            "description": (
                "This is the generic [DSO-compatible](https://aandeslagmetdeomgevingswet.nl/digitaal-stelsel/aansluiten/standaarden/api-en-uri-strategie/) API server.\n"  # noqa E501
                "\n"
                "The following features are supported:\n"
                "* HAL-JSON based links, pagination and response structure.\n"
                "* Use `?expand=name1,name2` to sideload specific relations.\n"
                "* Use `?expand=true` to sideload all relations.\n"
                "\n"
                "The models in this server are generated from the Amsterdam Schema files.\n"
                "These are located at: https://schemas.data.amsterdam.nl/datasets"
            ),
            # These fields can't be specified in get_schema_view():
            "termsOfService": "https://data.amsterdam.nl/",
            "contact": {"email": "datapunt@amsterdam.nl"},
            "license": {"name": "CC0 1.0 Universal"},
        },
        "servers": [{"url": settings.DATAPUNT_API_URL}],
        # While drf_spectacular parses authentication_classes, it won't
        # recognize oauth2 nor detect a remote authenticator. Adding manually:
        "security": [{"oauth2": []}],
        "components": {
            "securitySchemes": {
                "oauth2": {
                    "type": "oauth2",
                    "flows": {
                        "implicit": {
                            "authorizationUrl": "https://api.data.amsterdam.nl/oauth2/authorize",
                            "scopes": {"HR/R": "Toegang HR"},
                        }
                    },
                }
            }
        },
    }

    def get_schema(self, request=None, public=False):
        """Provide the missing data that DRF get_schema_view() doesn't yet offer."""
        schema = super().get_schema(request=request, public=public)
        schema["info"].update(self.extra_schema["info"])
        schema["components"].update(self.extra_schema["components"])
        schema["security"] = self.extra_schema["security"]

        if not settings.DEBUG:
            schema["servers"] = self.extra_schema["servers"]

        return schema


def _get_schema_view(renderer_classes=None):
    return get_schema_view(
        public=True,
        renderer_classes=renderer_classes,
        generator_class=ExtendedSchemaGenerator,
        permission_classes=(permissions.AllowAny,),
    )


urlpatterns = [
    path("status/health/", include(django_healthchecks.urls)),
    path("datasets/", include(dso_api.datasets.urls)),
    path("v1/", include(dso_api.dynamic_api.urls)),
    # path("v1/", schema_view.with_ui("swagger", cache_timeout=0)),
    path("v1/openapi.yaml", _get_schema_view([renderers.OpenAPIRenderer])),
    path("v1/openapi.json", _get_schema_view([renderers.JSONOpenAPIRenderer])),
    path("", RedirectView.as_view(url="/v1/"), name="root-redirect"),
]

handler400 = exceptions.bad_request
handler500 = exceptions.server_error


if "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns.extend([path("__debug__/", include(debug_toolbar.urls))])
