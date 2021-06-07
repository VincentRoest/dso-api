from graphene_django.views import GraphQLView

from dso_api.dynamic_api.schema import create_schema


def graphql(request):
    from dso_api.dynamic_api.urls import router

    schema = create_schema(router.all_models)

    return GraphQLView.as_view(schema=schema, graphiql=True)(request)
