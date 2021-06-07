from typing import List

import graphene
from django.contrib.gis.db.models.fields import GeometryField
from graphene import relay
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from graphene_django.filter import DjangoFilterConnectionField
from schematools.contrib.django.models import DynamicModel


def make_resolver(record_name, record_cls):
    def resolver(self, info):
        print(info)
        return info

    resolver.__name__ = "resolve_%s" % record_name
    return resolver


@convert_django_field.register(GeometryField)
def convert_json_field_to_string(field, registry=None):
    return graphene.String()


def create_schema(tables: List[DynamicModel]) -> graphene.Schema:
    record_schemas = {}
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
                    "filter_fields": {
                        "id": ["exact"],
                    }
                    if "id" in field_names
                    else {},
                    "interfaces": (relay.Node,),
                },
            )

            created_class = type(
                class_name,
                (DjangoObjectType,),
                {
                    "Meta": meta,
                },
            )

            print(created_class)

            record_schemas[class_name] = created_class

    # create Query in similar way
    fields = {}
    print(record_schemas)
    for key, rec in record_schemas.items():
        print(key, rec)
        fields[key] = relay.Node.Field(rec)
        fields[f"all_{key}"] = DjangoFilterConnectionField(rec)

    # according to relay spec we need to add root field node
    fields["node"] = relay.Node.Field()
    Query = type("Query", (graphene.ObjectType,), fields)

    return graphene.Schema(query=Query, types=list(record_schemas.values()))


# def create_schema(tables: List[DynamicModel]) -> graphene.Schema:
#     record_schemas = {}
#     field_types = set()
#     for table_name, table in tables.items():
#         for model_name, model in table.items():
#             fields = {}
#             classname = f"{table_name}_{model_name}"
#             for field in model._meta.get_fields():
#                 field_type = field.get_internal_type()
#                 # {'FloatField', 'BooleanField', 'ForeignKey',
#                 # 'TimeField', 'LooseRelationManyToManyField', 'MultiLineStringField',
#                 # 'CharField', 'DateTimeField', 'PointField', 'AutoField', 'LineStringField',
#                 # 'DateField', 'ManyToManyField', 'GeometryField', 'ArrayField',
#                 # 'BigIntegerField', 'MultiPolygonField', 'PolygonField'}

#                 field_types.add(field_type)
#                 # print(field_type, field)
#                 field_type_mapping = {
#                     "MultiLineStringField": graphene.String,
#                     "BigIntegerField": graphene.Int,
#                     "CharField": graphene.String,
#                     # "ArrayField": graphene.List,
#                     "DateTimeField": graphene.Date,
#                     "FloatField": graphene.Decimal,
#                     "BooleanField": graphene.Boolean,
#                     "MultiLineStringField": graphene.String,
#                     "LineStringField": graphene.String,
#                     "DateField": graphene.Date,
#                     "TimeField": graphene.Time,
#                     "GeometryField": graphene.JSONString,
#                     "MultiPolygonField": graphene.JSONString,
#                     "PolygonField": graphene.JSONString,
#                     "PointField": graphene.JSONString,
#                     "ForeignKey": graphene.Connection,
#                     "LooseRelationManyToManyField": graphene.Connection,
#                     "AutoField": graphene.ID
#                     # define types here
#                 }
#                 # graphql convention: no dots, no non-alphanumeric
#                 field_name = str(field).split(".")[-1]
#                 field_name = re.sub("[^0-9a-zA-Z_]+", "", field_name)

#                 # keyword
#                 if field_name == "class":
#                     field_name = "klasse"
#                 if field_name == "name":
#                     field_name = "naam"

#                 fields[field_name] = field_type_mapping.get(field_type, graphene.String)()

#             rec_cls = type(
#                 classname,
#                 (DjangoObjectType,),
#                 {"_meta": {model: model, fields: model._meta.get_fields()}},
#                 name=model.get_display_field(),
#                 description=model.get_dataset_schema().description,
#             )
#             record_schemas[classname] = rec_cls

#     print(field_types)
#     # create Query in similar way
#     fields = {}
#     for key, rec in record_schemas.items():
#         print(key, rec)
#         fields[key] = graphene.Field(rec)
#         fields["resolve_%s" % key] = make_resolver(key, rec)
#     Query = type("Query", (graphene.ObjectType,), fields)

#     return graphene.Schema(query=Query, types=list(record_schemas.values()))
