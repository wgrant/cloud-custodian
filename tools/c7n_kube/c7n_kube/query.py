# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import logging

from c7n.actions import ActionRegistry
from c7n.exceptions import PolicyValidationError
from c7n.filters import FilterRegistry
from c7n.manager import ResourceManager, ResourceQueryLifecycle
from c7n.query import _apply_augment_pipeline, sources
from c7n.utils import local_session

log = logging.getLogger("custodian.k8s.query")


class ResourceQuery:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def filter(self, resource_manager, **params):
        m = resource_manager.resource_type
        session = local_session(self.session_factory)
        client = session.client(m.group, m.version)

        enum_op, path, extra_args = m.enum_spec
        if extra_args:
            params.update(extra_args)
        return self._invoke_client_enum(client, enum_op, params, path)

    def _invoke_client_enum(self, client, enum_op, params, path):
        res = getattr(client, enum_op)(**params)
        if not isinstance(res, dict):
            res = res.to_dict()
        if path and path in res:
            res = res.get(path)
        return res


@sources.register("describe-kube")
class DescribeSource:
    def __init__(self, manager):
        self.manager = manager
        self.query = ResourceQuery(manager.session_factory)

    def get_resources(self, query):
        if query is None:
            query = {}
        return self.query.filter(self.manager, **query)

    def get_permissions(self):
        return ()

    def augment(self, resources):
        return resources


class QueryMeta(type):
    """metaclass to have consistent action/filter registry for new resources."""

    def __new__(cls, name, parents, attrs):
        if "filter_registry" not in attrs:
            attrs["filter_registry"] = FilterRegistry("%s.filters" % name.lower())
        if "action_registry" not in attrs:
            attrs["action_registry"] = ActionRegistry("%s.actions" % name.lower())

        return super(QueryMeta, cls).__new__(cls, name, parents, attrs)


class QueryResourceManager(ResourceQueryLifecycle, ResourceManager, metaclass=QueryMeta):
    augment_pipeline = None

    def __init__(self, ctx, data):
        super(QueryResourceManager, self).__init__(ctx, data)
        self.source = self.get_source(self.source_type)

    def get_permissions(self):
        return ()

    def get_source(self, source_type):
        return sources.get(source_type)(self)

    def get_client(self):
        client = local_session(self.session_factory).client(
            self.resource_type.group, self.resource_type.version
        )
        return client

    def get_model(self):
        return self.resource_type

    def get_cache_key(self, query):
        return {"source_type": self.source_type, "query": query}

    @property
    def source_type(self):
        return self.data.get("source", "describe-kube")

    def get_resource_query(self):
        if "query" in self.data:
            return {"filter": self.data.get("query")}

    def prepare_query(self, query):
        return query or self.get_resource_query()

    def fetch_resources(self, query):
        return self.source.get_resources(query)

    def augment(self, resources):
        return _apply_augment_pipeline(self, resources, self.augment_pipeline)


class CustomResourceQueryManager(QueryResourceManager, metaclass=QueryMeta):
    def get_resource_query(self):
        custom_resource = self.data["query"][0]
        return {
            "version": custom_resource["version"],
            "group": custom_resource["group"],
            "plural": custom_resource["plural"],
        }

    def validate(self):
        required_keys = {"group", "version", "plural"}
        if "query" not in self.data:
            raise PolicyValidationError(
                "Custom resources require query in policy with only "
                + "group, version, and plural attributes"
            )
        if set(list(self.data.get("query", [])[0].keys())) != required_keys:
            raise PolicyValidationError(
                "Custom resources require query in policy with only "
                + "group, version, and plural attributes"
            )
        return self


class TypeMeta(type):
    def __repr__(cls):
        return "<TypeInfo group:%s version:%s>" % (cls.group, cls.version)


class TypeInfo(metaclass=TypeMeta):
    group = None
    canonical_group = None
    version = None
    enum_spec = ()
    namespaced = True
    id = "metadata.uid"
    name = "metadata.name"


class CustomTypeInfo(TypeInfo, metaclass=TypeMeta):
    group = "CustomObjects"
    canonical_group = None
    version = ""
    enum_spec = ("list_cluster_custom_object", "items", None)
