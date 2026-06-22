# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import functools

from c7n.utils import chunks


def iter_pipeline_ops(ops):
    if ops is None:
        return ()
    if isinstance(ops, (list, tuple)):
        return ops
    return (ops,)


def get_raw_class_attr(owner, name):
    for cls in type(owner).__mro__:
        if name not in cls.__dict__:
            continue
        value = cls.__dict__[name]
        if isinstance(value, staticmethod):
            return value.__func__
        return value
    return None


def decorate_pipeline_func(role_attr, options_attr, role, func=None, **options):
    def decorate(f):
        if isinstance(f, staticmethod):
            f = f.__func__
        setattr(f, role_attr, role)
        setattr(f, options_attr, options)
        return staticmethod(f)

    if func is None:
        return decorate
    return decorate(func)


def iter_decorated_pipeline(owner, role_attr, options_attr):
    mro = list(type(owner).__mro__)
    for cls in reversed(mro):
        for name, value in cls.__dict__.items():
            if any(name in sub_cls.__dict__ for sub_cls in mro[:mro.index(cls)]):
                continue
            func = value.__func__ if isinstance(value, staticmethod) else value
            role = getattr(func, role_attr, None)
            if role is None:
                continue
            yield name, role, getattr(func, options_attr, {}), getattr(owner, name)


def build_decorated_pipeline(
        owner, role_attr, options_attr, factories, include=None, first=False):
    """Build operation objects from decorated methods on an owner.

    ``factories`` maps decorator roles to ``(handler, options) -> op`` callables.
    ``include`` can filter roles before factory lookup. Unknown roles are ignored,
    so domain layers can share discovery while owning their role vocabulary.
    Set ``first`` for domains that select a single decorated operation.
    """
    results = []
    for name, role, options, handler in iter_decorated_pipeline(
            owner, role_attr, options_attr):
        if include is not None and not include(role):
            continue
        if role not in factories:
            continue
        op = factories[role](handler, options)
        if first:
            return op
        results.append(op)
    if first:
        return None
    return results


def get_executor_context(context):
    if hasattr(context, 'executor_factory'):
        return context
    return context.manager


class FilterItems:
    """Filter items with a ``(context, item)`` predicate."""

    def __init__(self, predicate):
        self.predicate = predicate

    def __call__(self, context, resources):
        return [r for r in resources if self.predicate(context, r)]


class MutateItems:
    """Run a per-item mutator that changes items in place."""

    def __init__(self, func):
        self.func = func

    def __call__(self, context, resources):
        for resource in resources:
            self.func(context, resource)
        return resources


class MapItems:
    """Map one input item to zero or one output items."""

    def __init__(self, func, max_workers=None):
        self.func = func
        self.max_workers = max_workers

    def __call__(self, context, resources):
        results = []
        if self.max_workers:
            with get_executor_context(context).executor_factory(
                    max_workers=self.max_workers) as w:
                mapped_resources = w.map(
                    functools.partial(self.func, context), resources)
                for mapped in mapped_resources:
                    if mapped is not None:
                        results.append(mapped)
            return results

        for resource in resources:
            mapped = self.func(context, resource)
            if mapped is not None:
                results.append(mapped)
        return results


class MapBatch:
    """Map a batch of input items to zero or more output items."""

    def __init__(self, func, size=None, max_workers=None):
        self.func = func
        self.size = size
        self.max_workers = max_workers

    def __call__(self, context, resources):
        results = []
        resource_sets = chunks(resources, self.size) if self.size else (resources,)
        if self.max_workers:
            with get_executor_context(context).executor_factory(
                    max_workers=self.max_workers) as w:
                mapped_sets = w.map(
                    functools.partial(self.func, context),
                    resource_sets)
                for mapped in mapped_sets:
                    if mapped:
                        results.extend(mapped)
            return results

        for resource_set in resource_sets:
            mapped = self.func(context, resource_set)
            if mapped:
                results.extend(mapped)
        return results


class MutateBatch:
    """Run a mutator over batches and return the original item list."""

    def __init__(self, func, size=None, max_workers=None):
        self.func = func
        self.size = size
        self.max_workers = max_workers

    def __call__(self, context, resources):
        resource_sets = chunks(resources, self.size) if self.size else (resources,)
        if self.max_workers:
            with get_executor_context(context).executor_factory(
                    max_workers=self.max_workers) as w:
                list(w.map(functools.partial(self.func, context), resource_sets))
            return resources

        for resource_set in resource_sets:
            self.func(context, resource_set)
        return resources
