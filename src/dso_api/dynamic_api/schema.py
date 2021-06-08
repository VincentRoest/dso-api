from typing import List, Union

import graphene
from django.contrib.gis.db.models.fields import GeometryField
from graphene import relay
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from graphene_django.filter import DjangoFilterConnectionField
from graphql.type.definition import GraphQLResolveInfo
from rest_framework.viewsets import ViewSet
from schematools.contrib.django.models import DynamicModel
from schematools.utils import to_snake_case

from dso_api.dynamic_api.filterset import filterset_factory
from dso_api.dynamic_api.permissions import (
    fetch_scopes_for_model,
    get_permission_key_for_field,
    request_has_permission,
)


@convert_django_field.register(GeometryField)
# rest_framework_gis/fields.py
def convert_json_field_to_string(field, registry=None):
    return graphene.JSONString()


class CustomNode(relay.Node):
    class Meta:
        name = "Node"

    @staticmethod
    def to_global_id(type_, id):
        return f"{id}"

    @staticmethod
    def get_node_from_global_id(info, global_id, only_type=None):
        model = info.return_type.graphene_type._meta.model
        return model.objects.get(id=global_id)


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

    print(info.field_name)

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
            continue

        field_names = viewset.get_serializer_class(viewset).Meta.fields
        model = viewset.get_serializer_class(viewset).Meta.model
        if "name" in field_names or "class" in field_names:
            continue

        filterset = filterset_factory(model)
        print(filterset)
        # some error with csv filterset? Not working with graphene
        # print(model, field_names)

        meta = type(
            "Meta",
            (object,),
            {
                "model": model,
                "fields": "__all__",
                "serializer_class": viewset.get_serializer_class(viewset),
                # add actual filterable fields here.
                "filter_fields": {"id": ["exact"]} if "id" in field_names else {},
                # "filterset_class": filterset,
                "interfaces": (CustomNode,),
                "extra": {
                    "dataset_id": model.get_dataset_id(),
                    "table_id": model.get_table_id(),
                },
            },
        )

        if model.get_table_id() == "panden":
            print(str(model))
            print(model.get_table_id())
            print(model.get_dataset_id())

            print(
                [
                    f"resolve_{to_snake_case(field_name)}"
                    for field_name in field_names
                    if field_name != "_links"
                ]
            )

        # convert fieldnames to snake case
        field_names = [
            to_snake_case(field_name) if field_name != "_links" else field_name
            for field_name in field_names
        ]

        class_id = f"{model.get_dataset_id()}_{model.get_table_id()}"
        print(model, class_id)
        # https://medium.com/@jefmoura/how-to-secure-graphql-in-drf-without-duplicating-code-5a033599db17
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
        if class_id == "bag_panden":
            print(dir(created_class))
            print()

        record_schemas[class_id] = created_class

    # create Query in similar way
    fields = {}
    for key, rec in record_schemas.items():
        fields[key] = CustomNode.Field(rec)
        fields[f"all_{key}"] = DjangoFilterConnectionField(
            rec,  # filterset_class=filterset_factory(rec._meta.model)
        )
        # ssert isinstance(filter_field, BaseCSVFilter) -> error

        fields[f"resolve_{key}"] = lambda root, info, **kwargs: print("hi")

        # according to relay spec we need to add root field node
        fields["node"] = CustomNode.Field()

    Query = type("Query", (graphene.ObjectType,), fields)

    schema = graphene.Schema(
        query=Query,
        types=list(record_schemas.values()),
    )

    globals()["schema"] = schema
    return schema
