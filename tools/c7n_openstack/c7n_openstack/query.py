# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import logging

from c7n.actions import ActionRegistry
from c7n.filters import FilterRegistry
from c7n.manager import ResourceManager, ResourceQueryLifecycle
from c7n.query import _apply_augment_pipeline, sources
from c7n.utils import local_session

log = logging.getLogger('custodian.openstack.query')


class ResourceQuery:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def filter(self, resource_manager, **params):
        m = resource_manager.resource_type
        session = local_session(self.session_factory)
        client = session.client()

        enum_op, extra_args = m.enum_spec
        if extra_args:
            params.update(extra_args)
        return self._invoke_client_enum(client, enum_op, params)

    def _invoke_client_enum(self, client, enum_op, params):
        if isinstance(enum_op, list):
            obj = client
            res = []
            for op in enum_op:
                obj = getattr(obj, op)
            for r in obj(**params):
                res.append(r.toDict() if not isinstance(enum_op, dict) else r)
        else:
            res = getattr(client, enum_op)(**params)
        return res


@sources.register('describe-openstack')
class DescribeSource:
    augment_pipeline = None

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
        return _apply_augment_pipeline(
            self.manager, resources, self.augment_pipeline)


class QueryMeta(type):
    """metaclass to have consistent action/filter registry for new resources"""
    def __new__(cls, name, parents, attrs):
        if 'filter_registry' not in attrs:
            attrs['filter_registry'] = FilterRegistry(
                '%s.filters' % name.lower())
        if 'action_registry' not in attrs:
            attrs['action_registry'] = ActionRegistry(
                '%s.actions' % name.lower())

        return super(QueryMeta, cls).__new__(cls, name, parents, attrs)


class QueryResourceManager(ResourceQueryLifecycle, ResourceManager, metaclass=QueryMeta):

    source_mapping = sources
    augment_pipeline = None

    def __init__(self, ctx, data):
        super(QueryResourceManager, self).__init__(ctx, data)
        self.source = self.get_source(self.source_type)

    def get_permissions(self):
        return ()

    def get_source(self, source_type):
        if source_type in self.source_mapping:
            return self.source_mapping.get(source_type)(self)
        if source_type in sources:
            return sources.get(source_type)(self)
        raise KeyError("Invalid Source %s" % source_type)

    def get_client(self):
        client = local_session(self.session_factory).client()
        return client

    def get_model(self):
        return self.resource_type

    def get_cache_key(self, query):
        return {'source_type': self.source_type, 'query': query}

    @property
    def source_type(self):
        return self.data.get('source', 'describe-openstack')

    def get_resource_query(self):
        if 'query' in self.data:
            return {'filter': self.data.get('query')}

    def prepare_query(self, query):
        return query or self.get_resource_query()

    def fetch_resources(self, query):
        return self.source.get_resources(query)

    def handle_fetch_error(self, error, query):
        raise error

    def normalize_resources(self, resources, query):
        return resources

    def augment_resources(self, resources):
        return self.augment(resources)

    def should_cache_resources(self, query, resources, augment=True):
        return True

    def filter_resource_set(self, resources):
        return self.filter_resources(resources)

    def augment(self, resources):
        resources = self.source.augment(resources)
        return _apply_augment_pipeline(self, resources, self.augment_pipeline)


class TypeMeta(type):
    def __repr__(cls):
        return "<TypeInfo group:%s version:%s>" % (
            cls.group,
            cls.version)


class TypeInfo(metaclass=TypeMeta):
    enum_spec = ()
