Please read [UPGRADE-v2.0.md](https://github.com/graphql-python/graphene/blob/master/UPGRADE-v2.0.md) to learn how to upgrade to Graphene `2.0`.

---

# ![Graphene Logo](http://graphene-python.org/favicon.png) Graphene-Django


A [Django](https://www.djangoproject.com/) integration for [Graphene](http://graphene-python.org/).

[![travis][travis-image]][travis-url]
[![pypi][pypi-image]][pypi-url]
[![Anaconda-Server Badge][conda-image]][conda-url]
[![coveralls][coveralls-image]][coveralls-url]

[travis-image]: https://travis-ci.org/graphql-python/graphene-django.svg?style=flat
[travis-url]: https://travis-ci.org/graphql-python/graphene-django
[pypi-image]: https://img.shields.io/pypi/v/graphene-django.svg?style=flat
[pypi-url]: https://pypi.org/project/graphene-django/
[coveralls-image]: https://coveralls.io/repos/graphql-python/graphene-django/badge.svg?branch=master&service=github
[coveralls-url]: https://coveralls.io/github/graphql-python/graphene-django?branch=master
[conda-image]: https://img.shields.io/conda/vn/conda-forge/graphene-django.svg
[conda-url]: https://anaconda.org/conda-forge/graphene-django

## Documentation

[Visit the documentation to get started!](https://docs.graphene-python.org/projects/django/en/latest/)

## Quickstart

For installing graphene, just run this command in your shell

```bash
pip install "graphene-django>=2.0"
```

### Settings

```python
INSTALLED_APPS = (
    # ...
    'django.contrib.staticfiles', # Required for GraphiQL
    'graphene_django',
)

GRAPHENE = {
    'SCHEMA': 'app.schema.schema' # Where your Graphene schema lives
}
```

### Urls

We need to set up a `GraphQL` endpoint in our Django app, so we can serve the queries.

```python
from django.urls import path
from graphene_django.views import GraphQLView

urlpatterns = [
    # ...
    path('graphql', GraphQLView.as_view(graphiql=True)),
]
```

## Examples

Here is a simple Django model:

```python
from django.db import models

class UserModel(models.Model):
    name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
```

To create a GraphQL schema for it you simply have to write the following:

```python
from graphene_django import DjangoObjectType
import graphene

class User(DjangoObjectType):
    class Meta:
        model = UserModel

class Query(graphene.ObjectType):
    users = graphene.List(User)

    def resolve_users(self, info):
        return UserModel.objects.all()

schema = graphene.Schema(query=Query)
```

Then you can simply query the schema:

```python
query = '''
    query {
      users {
        name,
        lastName
      }
    }
'''
result = schema.execute(query)
```

To learn more check out the following [examples](examples/):

* **Schema with Filtering**: [Cookbook example](examples/cookbook)
* **Relay Schema**: [Starwars Relay example](examples/starwars)


## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## Release Notes

* See [Releases page on github](https://github.com/graphql-python/graphene-django/releases)


# 特定のテストだけ走らせる
py.test -s -v graphene_django/tests/test_query.py


# TODO
- inlineformset
- filefield clearable
- subscのvariables指定がうまくいくかとか
- async websocket consumersのcontext
