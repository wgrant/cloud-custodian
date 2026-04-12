# Copyright 2020 Cloud Custodian Authors.
# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from c7n import deprecated
from c7n.executor import ThreadPoolExecutor
from c7n.utils import jmespath_search


class Element:
    """Parent base class for filters and actions.
    """

    permissions = ()
    metrics = ()

    # Fallback used when no manager (and therefore no worker pool) is
    # available.  At runtime, the property below will delegate to the
    # manager's executor_factory so that filters and actions share the
    # central worker pool.
    _default_executor_factory = ThreadPoolExecutor

    @property
    def executor_factory(self):
        """Return the executor factory from the parent resource manager.

        When a manager is available its ``executor_factory`` is backed by
        the central ``WorkerPool`` (set up by ``ExecutionContext``).  If
        there is no manager — e.g. during standalone testing — fall back
        to the plain ``ThreadPoolExecutor`` class.

        An explicitly assigned value (via the setter) takes highest
        priority so that test patches on individual instances work.
        """
        # Check for an explicit per-instance override first.  This is
        # needed because data descriptors (property with __set__)
        # take precedence over the instance __dict__ during normal
        # attribute lookup.
        if 'executor_factory' in self.__dict__:
            return self.__dict__['executor_factory']
        manager = getattr(self, 'manager', None)
        if manager is not None and hasattr(manager, 'executor_factory'):
            return manager.executor_factory
        return self._default_executor_factory

    @executor_factory.setter
    def executor_factory(self, value):
        # Allow direct assignment (used by some tests that patch the
        # executor on a specific filter/action class or instance).
        self.__dict__['executor_factory'] = value

    schema = {'type': 'object'}
    # schema aliases get hoisted into a jsonschema definition
    # location, and then referenced inline.
    schema_alias = None

    def get_permissions(self):
        return self.permissions

    def validate(self):
        """Validate the current element's configuration.

        Should raise a validation error if there are any configuration issues.

        This method will always be called prior to element execution/process() method
        being called and thus can act as a point of lazy initialization.
        """

    def filter_resources(self, resources, key_expr, allowed_values=()):
        # many filters implementing a resource state transition only allow
        # a given set of starting states, this method will filter resources
        # and issue a warning log, as implicit filtering in filters means
        # our policy metrics are off, and they should be added as policy
        # filters.
        resource_count = len(resources)
        search_expr = key_expr
        if not search_expr.startswith('[].'):
            search_expr = '[].' + key_expr
        results = [r for value, r in zip(
            jmespath_search(search_expr, resources), resources)
            if value in allowed_values]
        if resource_count != len(results):
            self.log.warning(
                "%s implicitly filtered %d of %d resources key:%s on %s",
                self.type, len(results), resource_count, key_expr,
                (', '.join(map(str, allowed_values))))
        return results

    def get_deprecations(self):
        """Return any matching deprecations for the policy fields itself."""
        return deprecated.check_deprecations(self, self.type + ":")
