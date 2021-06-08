from typing import List

from graphene_django.views import GraphQLView
from graphql.type.definition import GraphQLResolveInfo

from dso_api.dynamic_api.schema import create_schema


def recurse_selections(node, current_id: str) -> str:
    if node.selection_set and node.selection_set.selections:
        for selection in node.selection_set.selections:
            return recurse_selections(selection, current_id=f"{current_id}.{selection.name.value}")
    else:
        return f"{current_id}"

    return current_id


def get_auth_id(info: GraphQLResolveInfo) -> List[str]:
    auth_strs = []
    for field_node in info.field_nodes:
        auth_str = field_node.name.value
        auth_strs.extend([recurse_selections(field_node, auth_str)])

    return auth_strs


class AuthorizationMiddleware:
    def resolve(self, next, root, info, **args):
        return next(root, info, **args)
        """
        request = info.context
        # TODO
        ## handle multiple queries top level
        auth_ids = get_auth_id(info)[0]

        print(f"resolving field: {info.parent_type}.{auth_ids}")
        if str(info.parent_type) == "Query":
            # apply table permissions
            table_name = info.field_name.replace("all", "")
            table_name = re.sub(r"(?<!^)(?=[A-Z])", "_", table_name).lower()
            table_auth = fetch_scopes_for_dataset_table(
                table_name.split("_")[0], "".join(table_name.split("_")[1:])
            )
            print("Non-leaf")

        # root node
        elif len(auth_ids[0].split(".")) == 1:
            print("Leaf field")
        """


def graphql(request):
    from dso_api.dynamic_api.urls import router

    schema = create_schema(router.all_viewsets)

    try:
        return GraphQLView.as_view(
            schema=schema,
            graphiql=True,
        )(request)
    except Exception as e:
        # 500 error
        print(e)
