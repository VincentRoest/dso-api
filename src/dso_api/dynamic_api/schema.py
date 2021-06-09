from typing import List, Union

import graphene
from django.contrib.gis.db.models.fields import GeometryField
from django.contrib.postgres.fields.array import ArrayField
from graphene import relay
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from graphene_django.filter import DjangoFilterConnectionField
from graphql.type.definition import GraphQLResolveInfo
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.viewsets import ViewSet
from schematools.contrib.django.models import DynamicModel
from schematools.utils import to_snake_case, toCamelCase

from dso_api.dynamic_api.filterset import filterset_factory
from dso_api.dynamic_api.permissions import (
    fetch_scopes_for_model,
    get_permission_key_for_field,
    request_has_permission,
)
from dso_api.dynamic_api.views.api import DynamicApiViewSet


@convert_django_field.register(GeometryField)
# rest_framework_gis/fields.py
def convert_json_field_to_string(field, registry=None):
    return graphene.JSONString()


class CustomNode(relay.Node):
    class Meta:
        name = "Node"

    @staticmethod
    def to_global_id(type_, id):
        return f"{type_}:{id}"

    @staticmethod
    def get_node_from_global_id(info, global_id, only_type=None):
        model = info.return_type.graphene_type._meta.model
        return model.objects.get(id=global_id)


def resolve_remote(
    root: DjangoObjectType, info: GraphQLResolveInfo, viewset: DynamicApiViewSet, *args, **kwargs
):
    viewset.action_map = {"post": "retrieve", "get": "retrieve"}
    view = viewset()
    print(info)
    print(*args)
    print({k: f for k, f in kwargs.items()})
    print(viewset.client._endpoint_url)
    # view.format_kwarg = "application/json"  # ??
    request = Request(
        info.context,
        parsers=view.get_parsers(),
        authenticators=view.get_authenticators(),
        parser_context=view.get_parser_context(info.context),
    )

    view.request = request
    view.format_kwarg = {}

    view.check_permissions(request)

    print(view.get_parsers())
    print(view.get_parser_context(info.context))

    request.accepted_renderer = JSONRenderer

    # print(vars(view))
    # # print(view._negotiator.get_accept_list(request))

    # # get apparently only lookup on 1 field is possible in Client: pk
    view.kwargs = {"pk": kwargs["bsn"]}
    data = view.client.call(info.context, path=f"{kwargs['bsn']}")

    serializer = view.get_serializer(data=data, context={"request": request}, many=False)
    print(serializer)
    # Class SuwiVerzoekenSerializer missing \"Meta.model\" attribute
    try:
        serializer.is_valid()
    except Exception as e:
        print(e)
        pass

    serializer.save()
    # view.kwargs = {"pk": variables["bsn"]}
    return serializer.save()


def field_based_auth(
    root: DjangoObjectType, info: GraphQLResolveInfo, model: DynamicModel
) -> Union[DjangoObjectType, None]:
    """Adds field based authorization on a field in the GraphQL Schema based on the Model scopes
    defined by the Amsterdam Schema.

    Args:
        root (DjangoObjectType): The Object that is about to be resolved
        info (GraphQLResolveInfo): Contains the request of the root + user info
        model_scopes (TableScopes): The TableScopes for this particular model

    Returns:
        Union[DjangoObjectType, None]: If allowed, return resolved value else None
    """
    request = info.context
    model_scopes = fetch_scopes_for_model(model)

    # profiles need testing
    request.auth_profile.valid_query_params = (
        # + view.table_schema.identifier
        request.auth_profile.get_valid_query_params()
    )

    active_profiles = request.auth_profile.get_active_profiles(
        model.get_dataset_id(), model.get_table_id()
    )

    print(f"field_auth {info.field_name}")

    field_name = to_snake_case(info.field_name)

    OK = getattr(root, to_snake_case(field_name))
    DENY = None

    if active_profiles:
        return OK

    if not hasattr(request, "is_authorized_for"):
        return DENY

    required = model_scopes.table
    field_scope = model_scopes.fields.get(field_name)
    if field_scope is not None:
        required = required | set([field_scope])

    if not request.is_authorized_for(*required):
        permission_key = get_permission_key_for_field(field_name)
        if not request_has_permission(request=request, perm=permission_key):
            return DENY

    return OK


schema = None


def create_schema(viewsets: List[ViewSet]) -> graphene.Schema:
    record_schemas = {}
    if globals()["schema"]:
        print("Using cached schema")
        return globals()["schema"]

    for viewset_name, viewset in viewsets.items():
        if viewset_name.startswith("remote"):
            if "hcbrk" in viewset_name:
                continue

            model = getattr(viewset, "model")
            field_names = viewset.serializer_class.Meta.fields

            meta = type(
                "Meta",
                (object,),
                {
                    "model": getattr(viewset, "model"),
                    "fields": "__all__",
                    "serializer_class": viewset.serializer_class,
                    # add actual filterable fields here.
                    "filterset_class": viewset.filterset_class,
                    "interfaces": (CustomNode,),
                },
            )

            class_id = toCamelCase(viewset_name.replace("-", "_"))
            print(field_names)
            created_class = type(
                class_id,
                (DjangoObjectType,),
                {
                    "Meta": meta,
                },
            )

            record_schemas[class_id] = created_class
        else:
            field_names = viewset.get_serializer_class(viewset).Meta.fields
            model = viewset.get_serializer_class(viewset).Meta.model
            if "name" in field_names or "class" in field_names:
                continue

            filterset = filterset_factory(model)
            # filter_types = filterset.get_filters()

            meta = type(
                "Meta",
                (object,),
                {
                    "model": model,
                    "fields": "__all__",
                    "serializer_class": viewset.get_serializer_class(viewset),
                    # add actual filterable fields here.
                    "filter_fields": {
                        field: filter_expr
                        for field, filter_expr in filterset.get_fields().items()
                        if not isinstance(model._meta.get_field(field), GeometryField)
                        and not isinstance(model._meta.get_field(field), ArrayField)
                    }
                    if "id" in field_names
                    else {},
                    # "filterset_class": filterset,
                    "interfaces": (CustomNode,),
                    "extra": {
                        "dataset_id": model.get_dataset_id(),
                        "table_id": model.get_table_id(),
                    },
                },
            )

            # convert fieldnames to snake case
            field_names = [
                to_snake_case(field_name) if field_name != "_links" else field_name
                for field_name in field_names
            ]

            class_id = f"{model.get_dataset_id()}_{model.get_table_id()}"

            created_class = type(
                class_id,
                (DjangoObjectType,),
                {
                    "Meta": meta,
                    # add table authorization
                    # TODO
                    # table auth?
                    # adding field based authorization
                    **{
                        f"resolve_{field_name}": lambda root, info: field_based_auth(
                            root,
                            info,
                            model,
                        )
                        for field_name in field_names
                    },
                },
            )
            record_schemas[class_id] = created_class

    # create Query in similar way
    fields = {}
    for key, rec in record_schemas.items():
        if not key.startswith("remote"):
            fields[key] = CustomNode.Field(rec)
            fields[f"all_{key}"] = DjangoFilterConnectionField(rec)
        else:
            # remoteSuwiVerzoeken =>
            viewset_name = to_snake_case(key).replace("_", "-")
            print(dir(viewsets[viewset_name]))

            # fields[key] = DjangoFilterConnectionField(rec)
            fields[key] = graphene.Field(
                rec,
                bsn=graphene.String(required=True),
                resolver=lambda root, info, *args, **kwargs: resolve_remote(
                    root, info, viewsets[viewset_name], *args, **kwargs
                ),
            )

        # ssert isinstance(filter_field, BaseCSVFilter) -> error

    # according to relay spec we need to add root field node
    fields["node"] = CustomNode.Field()

    Query = type("Query", (graphene.ObjectType,), fields)

    schema = graphene.Schema(
        query=Query,
        types=list(record_schemas.values()),
    )

    globals()["schema"] = schema
    return schema
