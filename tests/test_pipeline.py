# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.pipeline import (
    FilterItems, MapBatches, MapItems, MutateBatches, MutateItems,
    build_decorated_pipeline, decorate_pipeline_func, get_raw_class_attr,
    iter_decorated_pipeline, iter_pipeline_ops,
)


class Executor:
    def __init__(self, context, max_workers):
        self.context = context
        self.max_workers = max_workers

    def __enter__(self):
        self.context.workers.append(self.max_workers)
        return self

    def __exit__(self, *exc_info):
        return False

    def map(self, func, resources):
        return map(func, resources)


class Context:
    def __init__(self):
        self.workers = []

    def executor_factory(self, max_workers):
        return Executor(self, max_workers)


class FilterContext:
    def __init__(self):
        self.manager = Context()


def test_iter_pipeline_ops():
    op = object()

    assert iter_pipeline_ops(None) == ()
    assert iter_pipeline_ops(op) == (op,)
    assert iter_pipeline_ops([op]) == [op]
    assert iter_pipeline_ops((op,)) == (op,)


def test_get_raw_class_attr_staticmethod_and_overrides():
    class Base:
        value = 'base'

        @staticmethod
        def func():
            return 'base'

    class Child(Base):
        value = 'child'

    child = Child()

    assert get_raw_class_attr(child, 'value') == 'child'
    assert get_raw_class_attr(child, 'func') is Base.__dict__['func'].__func__
    assert get_raw_class_attr(child, 'missing') is None


def test_iter_decorated_pipeline_order_options_and_override():
    def decorate(role, func=None, **options):
        return decorate_pipeline_func('role', 'options', role, func, **options)

    class Base:
        @decorate('mutate')
        def first(self, resource):
            return resource

        @decorate('map', size=2)
        def replaced(self, resource):
            return resource

    class Child(Base):
        def replaced(self, resource):
            return resource

        @decorate('batch', max_workers=3)
        def last(self, resources):
            return resources

    child = Child()
    results = list(iter_decorated_pipeline(child, 'role', 'options'))

    assert [(n, r, o) for n, r, o, h in results] == [
        ('first', 'mutate', {}),
        ('last', 'batch', {'max_workers': 3}),
    ]
    assert results[0][3](child, 'resource') == 'resource'


def test_build_decorated_pipeline_filters_and_builds_ops():
    def decorate(role, func=None, **options):
        return decorate_pipeline_func('role', 'options', role, func, **options)

    class Owner:
        @decorate('keep', size=2)
        def first(self, resource):
            return resource

        @decorate('drop')
        def second(self, resource):
            return resource

    owner = Owner()
    ops = build_decorated_pipeline(
        owner, 'role', 'options',
        {'keep': lambda handler, options: (handler, options)},
        include=lambda role: role != 'drop')

    assert len(ops) == 1
    assert ops[0][0](owner, 'resource') == 'resource'
    assert ops[0][1] == {'size': 2}


def test_build_decorated_pipeline_first_returns_first_op():
    def decorate(role, func=None, **options):
        return decorate_pipeline_func('role', 'options', role, func, **options)

    class Owner:
        @decorate('one')
        def first(self, resource):
            return 'first'

        @decorate('two')
        def second(self, resource):
            return 'second'

    op = build_decorated_pipeline(
        Owner(), 'role', 'options',
        {
            'one': lambda handler, options: handler,
            'two': lambda handler, options: handler,
        },
        first=True)

    assert op(None, None) == 'first'


def test_filter_items():
    assert FilterItems(lambda context, r: r % 2)(None, [1, 2, 3]) == [1, 3]


def test_mutate_items_returns_same_list():
    resources = [{'name': 'one'}]

    def mark(context, resource):
        resource['seen'] = True

    assert MutateItems(mark)(None, resources) is resources
    assert resources == [{'name': 'one', 'seen': True}]


def test_map_items_drops_none():
    def odd(context, resource):
        if resource % 2:
            return {'value': resource}

    assert MapItems(odd)(None, [1, 2, 3]) == [{'value': 1}, {'value': 3}]


def test_map_items_uses_executor():
    context = Context()

    def double(context, resource):
        return resource * 2

    assert MapItems(double, max_workers=2)(context, [1, 2]) == [2, 4]
    assert context.workers == [2]


def test_map_batches_chunks_flattens_and_skips_empty_results():
    seen = []

    def odds(context, resource_set):
        seen.append(list(resource_set))
        return [{'value': r} for r in resource_set if r % 2]

    assert MapBatches(odds, size=2)(None, [1, 2, 3, 4]) == [
        {'value': 1}, {'value': 3}]
    assert seen == [[1, 2], [3, 4]]


def test_map_batches_uses_filter_context_executor():
    resource_filter = FilterContext()

    def values(resource_filter, resource_set):
        return list(resource_set)

    assert MapBatches(values, size=2, max_workers=4)(
        resource_filter, [1, 2, 3]) == [1, 2, 3]
    assert resource_filter.manager.workers == [4]


def test_mutate_batches_returns_same_list_and_uses_executor():
    context = Context()
    resources = [{'value': 1}, {'value': 2}, {'value': 3}]
    seen = []

    def mark(context, resource_set):
        seen.append([r['value'] for r in resource_set])
        for resource in resource_set:
            resource['seen'] = True

    assert MutateBatches(mark, size=2, max_workers=3)(context, resources) is resources
    assert seen == [[1, 2], [3]]
    assert context.workers == [3]
    assert resources == [
        {'value': 1, 'seen': True},
        {'value': 2, 'seen': True},
        {'value': 3, 'seen': True}]
