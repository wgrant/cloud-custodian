# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from collections import deque
import logging

from c7n import cache, deprecated
from c7n.executor import ThreadPoolExecutor
from c7n.provider import clouds
from c7n.registry import PluginRegistry
from c7n.resources import load_resources
try:
    from c7n.resources.aws import AWS
    resources = AWS.resources
except ImportError:
    resources = PluginRegistry('resources')

from c7n.utils import dumps


def iter_filters(filters, block_end=False):
    queue = deque(filters)
    while queue:
        f = queue.popleft()
        if f is not None and f.type in ('or', 'and', 'not'):
            if block_end:
                queue.appendleft(None)
            for gf in f.filters:
                queue.appendleft(gf)
        yield f


class ResourceManager:
    """
    A Cloud Custodian resource
    """

    filter_registry = None
    action_registry = None
    executor_factory = ThreadPoolExecutor
    retry = None
    permissions = ()
    get_client = None
    get_schema = None

    def __init__(self, ctx, data):
        self.ctx = ctx
        self.session_factory = ctx.session_factory
        self.config = ctx.options
        self.data = data
        self._cache = cache.factory(self.ctx.options)
        self.log = logging.getLogger('custodian.resources.%s' % (
            self.__class__.__name__.lower()))

        if self.filter_registry:
            self.filters = self.filter_registry.parse(
                self.data.get('filters', []), self)
        if self.action_registry:
            self.actions = self.action_registry.parse(
                self.data.get('actions', []), self)

    def format_json(self, resources, fh):
        return dumps(resources, fh, indent=2)

    def match_ids(self, ids):
        """return ids that match this resource type's id format."""
        return ids

    @classmethod
    def get_permissions(cls):
        return ()

    def get_resources(self, resource_ids):
        """Retrieve a set of resources by id."""
        return []

    def resources(self):
        raise NotImplementedError("")

    def get_resource_manager(self, resource_type, data=None):
        """get a resource manager or a given resource type.

        assumes the query is for the same underlying cloud provider.
        """
        if '.' in resource_type:
            provider_name, resource_type = resource_type.split('.', 1)
        else:
            provider_name = self.ctx.policy.provider_name

        # check and load
        load_resources(('%s.%s' % (provider_name, resource_type),))
        provider_resources = clouds[provider_name].resources
        klass = provider_resources.get(resource_type)
        if klass is None:
            raise ValueError(resource_type)

        # if we're already querying via config carry it forward
        if not data and self.source_type == 'config' and getattr(
                klass.get_model(), 'config_type', None):
            return klass(self.ctx, {'source': self.source_type})
        return klass(self.ctx, data or {})

    def filter_resources(self, resources, event=None):
        original = len(resources)
        if event and event.get('debug', False):
            self.log.info(
                "Filtering resources using %d filters", len(self.filters))
        for idx, f in enumerate(self.filters, start=1):
            if not resources:
                break
            rcount = len(resources)

            with self.ctx.tracer.subsegment("filter:%s" % f.type):
                resources = f.process(resources, event)

            if event and event.get('debug', False):
                self.log.debug(
                    "Filter #%d applied %d->%d filter: %s",
                    idx, rcount, len(resources), dumps(f.data, indent=None))
        self.log.debug("Filtered from %d to %d %s" % (
            original, len(resources), self.__class__.__name__.lower()))
        return resources

    def get_model(self):
        """Returns the resource meta-model.
        """
        return self.query.resolve(self.resource_type)

    def iter_filters(self, block_end=False):
        return iter_filters(self.filters, block_end=block_end)

    def validate(self):
        """
        Validates resource definition, does NOT validate filters, actions, modes.

        Example use case: A resource type that requires an additional query

        :example:

        .. code-block:: yaml

            policies:
              - name: k8s-custom-resource
                resource: k8s.custom-namespaced-resource
                query:
                  - version: v1
                    group stable.example.com
                    plural: crontabs
        """
        pass

    def get_deprecations(self):
        """Return any matching deprecations for the resource itself."""
        return deprecated.check_deprecations(self)


class ResourceQueryLifecycle:
    """Shared resource enumeration lifecycle for provider query managers."""

    def prepare_query(self, query):
        return query

    def fetch_resources(self, query):
        raise NotImplementedError("")

    def handle_fetch_error(self, error, query):
        raise error

    def normalize_resources(self, resources, query):
        return resources

    def augment_resources(self, resources):
        return self.augment(resources)

    def should_cache_resources(self, query, resources, augment):
        return True

    def filter_resource_set(self, resources):
        return self.filter_resources(resources)

    def get_resource_cache_key(self, query):
        if not hasattr(self, 'get_cache_key'):
            return None
        return self.get_cache_key(query)

    def get_cached_query_resources(self, cache_key):
        if cache_key is None:
            return None
        resources = self._cache.get(cache_key)
        if resources is not None:
            self.log.debug("Using cached %s: %d" % (
                "%s.%s" % (self.__class__.__module__, self.__class__.__name__),
                len(resources)))
        return resources

    def save_cached_query_resources(self, cache_key, resources):
        if cache_key is not None:
            self._cache.save(cache_key, resources)

    def check_resource_query_limits(self, resources, resource_count):
        if self.data == self.ctx.policy.data and hasattr(self, 'check_resource_limit'):
            self.check_resource_limit(len(resources), resource_count)

    def resources(self, query=None, augment=True):
        query = self.prepare_query(query)
        cache_key = self.get_resource_cache_key(query)
        resources = None

        with self._cache:
            resources = self.get_cached_query_resources(cache_key)
            if resources is None:
                try:
                    resources = self.fetch_resources(query)
                except Exception as e:
                    resources = self.handle_fetch_error(e, query)
                resources = self.normalize_resources(resources, query)
                if augment:
                    resources = self.augment_resources(resources)
                if self.should_cache_resources(query, resources, augment):
                    self.save_cached_query_resources(cache_key, resources)

        resource_count = len(resources)
        resources = self.filter_resource_set(resources)
        self.check_resource_query_limits(resources, resource_count)
        return resources


class SyntheticResourceMixin:
    """Resource manager helper for singleton or computed resources.

    These resources are not enumerated through a provider query API, but they
    still participate in normal resource filtering.
    """

    def get_synthetic_resources(self, query=None):
        raise NotImplementedError("")

    def get_synthetic_resources_by_ids(self, resource_ids):
        return self.get_synthetic_resources()

    def resources(self, query=None, augment=True):
        resources = self.get_synthetic_resources(query)
        if hasattr(self, 'filter_resources'):
            resources = self.filter_resources(resources)
        return resources

    def get_resources(self, resource_ids, cache=True, augment=True):
        return self.get_synthetic_resources_by_ids(resource_ids)
