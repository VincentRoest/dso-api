from typing import List, Union

import graphene
from django.contrib.gis.db.models.fields import GeometryField
from graphene import relay
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from graphene_django.filter import DjangoFilterConnectionField
from graphql.type.definition import GraphQLResolveInfo
from schematools.contrib.django.models import DatasetTable, DynamicModel
from schematools.utils import to_snake_case

from dso_api.dynamic_api.permissions import (
    fetch_scopes_for_model,
    get_permission_key_for_field,
    request_has_permission,
)


@convert_django_field.register(GeometryField)
# rest_framework_gis/fields.py
def convert_json_field_to_string(field, registry=None):
    return graphene.JSONString()


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
    print(active_profiles)

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


def create_schema(tables: List[DatasetTable]) -> graphene.Schema:
    record_schemas = {}
    if globals()["schema"]:
        print("Using cached schema")
        return globals()["schema"]

    for table_name, table in tables.items():
        for model_name, model in table.items():
            class_name = f"{table_name}_{model_name}"

            # for removing keywords from class defs
            field_names = [str(f).split(".")[-1] for f in model._meta.get_fields()]
            if "name" in field_names or "class" in field_names:
                continue

            meta = type(
                "Meta",
                (object,),
                {
                    "model": model,
                    "fields": "__all__",
                    # add actual filterable fields here.
                    # filterset_class?
                    "filter_fields": {
                        "id": ["exact"],
                    }
                    if "id" in field_names
                    else {},
                    "interfaces": (relay.Node,),
                    "extra": {
                        "dataset_id": model.get_dataset_id(),
                        "table_id": model.get_table_id(),
                    },
                },
            )

            created_class = type(
                class_name,
                (DjangoObjectType,),
                {
                    "Meta": meta,
                    # add table authorization
                    # TODO
                    f"resolve_{table_name}": lambda root, info: field_based_auth(
                        root,
                        info,
                        model,
                    ),
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

            record_schemas[class_name] = created_class

    # create Query in similar way
    fields = {}
    for key, rec in record_schemas.items():
        fields[key] = relay.Node.Field(rec)
        fields[f"all_{key}"] = DjangoFilterConnectionField(rec)

    # according to relay spec we need to add root field node
    fields["node"] = relay.Node.Field()
    Query = type("Query", (graphene.ObjectType,), fields)

    schema = graphene.Schema(
        query=Query,
        types=list(record_schemas.values()),
    )

    globals()["schema"] = schema
    return schema
