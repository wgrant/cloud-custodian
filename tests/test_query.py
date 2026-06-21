# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import json
import logging
import os


from c7n.query import (
    AnnotateParent, DescribeSource, FilterResources, MapBatch, MapResource,
    MergeField, MutateResource, ResourceQuery, RetryPageIterator, TagsFromApi,
    TagsFromField, TypeInfo, apply_augment_pipeline,
    apply_source_augment_pipeline, apply_tag_augment, augment,
)
from c7n.resources.vpc import InternetGateway

from botocore.config import Config
from .common import BaseTest, placebo_dir


class ResourceQueryTest(BaseTest):

    def test_pager_with_throttles(self):
        session_factory = self.replay_flight_data('test_query_pagination_retry')
        # at the time of test authoring, there were no retries in the sdk for
        # the describe log groups api, however we also want to override on any
        # sdk config files for unit tests, as well future proof on sdk retry
        # data file updates.
        client = session_factory().client(
            'logs', config=Config(retries={'max_attempts': 0}))

        if self.recording:
            data = json.load(
                open(
                    os.path.join(
                        placebo_dir('test_log_group_last_write'),
                        'logs.DescribeLogGroups_1.json')))
            data['data']['nextToken'] = 'moreplease+kthnxbye'
            self.pill.save_response(
                'logs', 'DescribeLogGroups', data['data'], http_response=200)

            self.pill.save_response(
                'logs', 'DescribeLogGroups',
                {'ResponseMetadata': {
                    "RetryAttempts": 0,
                    "HTTPStatusCode": 200,
                    "RequestId": "dc1f3c1e-a41d-11e6-a2a7-1fd802fe6512",
                    "HTTPHeaders": {
                        "x-amzn-requestid": "dc1f3c1e-a41d-11e6-a2a7-1fd802fe6512",
                        "date": "Sun, 06 Nov 2016 12:38:02 GMT",
                        "content-length": "1621",
                        "content-type": "application/x-amz-json-1.1"
                    }},
                 'Error': {'Code': 'ThrottlingException'}},
                http_response=400)

            self.pill.save_response(
                'logs', 'DescribeLogGroups',
                json.load(
                    open(
                        os.path.join(
                            placebo_dir('test_log_group_retention'),
                            'logs.DescribeLogGroups_1.json')))['data'],
                http_response=200)
            return

        paginator = client.get_paginator('describe_log_groups')
        paginator.PAGE_ITERATOR_CLS = RetryPageIterator
        results = paginator.paginate().build_full_result()
        self.assertEqual(len(results['logGroups']), 11)

    def test_query_filter(self):
        session_factory = self.replay_flight_data("test_query_filter")
        p = self.load_policy(
            {"name": "ec2", "resource": "ec2"}, session_factory=session_factory
        )
        q = ResourceQuery(p.session_factory)
        resources = q.filter(p.resource_manager)
        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["Instances"][0]["InstanceId"], "i-9432cb49")

    def test_query_get(self):
        session_factory = self.replay_flight_data("test_query_get")
        p = self.load_policy(
            {"name": "ec2", "resource": "ec2"}, session_factory=session_factory
        )
        q = ResourceQuery(p.session_factory)
        resources = q.get(p.resource_manager, ["i-9432cb49"])
        self.assertEqual(len(resources), 1)
        self.assertEqual(
            resources[0]["Instances"][0]["InstanceId"], "i-9432cb49")

    def test_query_model_get(self):
        session_factory = self.replay_flight_data("test_query_model")
        p = self.load_policy(
            {"name": "igw", "resource": "internet-gateway"},
            session_factory=session_factory,
        )
        q = ResourceQuery(p.session_factory)
        resources = q.filter(p.resource_manager)
        self.assertEqual(len(resources), 3)
        resources = q.get(p.resource_manager, ["igw-3d9e3d56"])
        self.assertEqual(len(resources), 1)

    def test_type_info(self):
        assert repr(TypeInfo) == "<TypeInfo TypeInfo>"


class ConfigSourceTest(BaseTest):

    def test_config_select(self):
        pass

    def test_config_get_query(self):
        p = self.load_policy({'name': 'x', 'resource': 'ec2'})
        source = p.resource_manager.get_source('config')

        # if query passed in reflect it back
        self.assertEqual(
            source.get_query_params({'expr': 'select 1'}),
            {'expr': 'select 1'})

        # if no query passed reflect back policy data
        p.data['query'] = [{'expr': 'select configuration'}]
        self.assertEqual(
            source.get_query_params(None), {'expr': 'select configuration'})

        p.data.pop('query')

        # default query construction
        self.assertTrue(
            source.get_query_params(None)['expr'].startswith(
                'select resourceId, configuration, supplementaryConfiguration where resourceType'))

        p.data['query'] = [{'clause': "configuration.imageId = 'xyz'"}]
        self.assertIn("imageId = 'xyz'", source.get_query_params(None)['expr'])


class AugmentPipelineTest(BaseTest):

    def test_source_query_default_on_source(self):
        class Manager:
            session_factory = None

            class config:
                account_id = '123456789012'

        class Source(DescribeSource):
            @staticmethod
            def get_account_id(source):
                return source.manager.config.account_id

            source_query_default = {
                'AccountId': get_account_id,
                'Language': 'en'}

        source = Source(Manager())

        self.assertEqual(
            source.get_query_params({'Language': 'fr'}),
            {'AccountId': '123456789012', 'Language': 'fr'})
        self.assertEqual(
            source.prepare_query(None),
            {'AccountId': '123456789012', 'Language': 'en'})

    def test_source_query_default_on_manager(self):
        class Manager:
            session_factory = None
            source_query_default = {'AccountId': '123456789012'}

        source = DescribeSource(Manager())

        self.assertEqual(
            source.get_query_params({}),
            {'AccountId': '123456789012'})

    def test_source_query_default_callable_can_skip_query(self):
        class Manager:
            session_factory = None

        class Source(DescribeSource):
            @staticmethod
            def skip_query(source):
                return None

            source_query_default = skip_query

        source = Source(Manager())

        self.assertIsNone(source.prepare_query({}))

    def test_source_resources_prepared_skips_query_defaults(self):
        queries = []

        class Manager:
            session_factory = None

        class Source(DescribeSource):
            source_query_default = {'AccountId': '123456789012'}

            def get_query(self):
                return None

            def fetch_resources(self, query):
                queries.append(query)
                return []

        source = Source(Manager())

        source.resources({}, prepared=True)
        source.resources({})

        self.assertEqual(
            queries,
            [{}, {'AccountId': '123456789012'}])

    def test_merge_field(self):
        resources = [{'Name': 'cluster', 'Provisioned': {'Name': 'nested', 'Size': 3}}]

        self.assertEqual(
            MergeField('Provisioned', remove=False, overwrite=False)(None, resources),
            [{'Name': 'cluster', 'Provisioned': {'Name': 'nested', 'Size': 3}, 'Size': 3}])

    def test_merge_field_removes_source(self):
        resources = [{'SamplingRule': {'RuleName': 'default', 'Priority': 1000}}]

        self.assertEqual(
            MergeField('SamplingRule')(None, resources),
            [{'RuleName': 'default', 'Priority': 1000}])

    def test_merge_field_skips_missing(self):
        resources = [{'Name': 'resource'}]

        self.assertEqual(MergeField('Provisioned')(None, resources), resources)

    def test_tags_from_field_merge(self):
        resources = [{'Tags': [{'Key': 'Owner', 'Value': 'Policy'}],
                      'tags': {'App': 'Custodian'}}]

        self.assertEqual(
            TagsFromField('tags', remove=True, missing='empty', merge=True)(
                None, resources),
            [{'Tags': [
                {'Key': 'Owner', 'Value': 'Policy'},
                {'Key': 'App', 'Value': 'Custodian'}]}])

    def test_tags_from_api_drop_on_error_allows_empty_result(self):
        class Client:
            def list_tags_for_resource(self, ResourceArn):
                return None

        class Manager:
            def get_client(self):
                return Client()

            def retry(self, func, ignore_err_codes=(), **kw):
                return func(**kw)

            class resource_type:
                arn = 'Arn'

        resources = [{'Arn': 'arn:missing'}]

        self.assertEqual(
            TagsFromApi(drop_on_error=True)(Manager(), resources),
            [])

    def test_filter_resources(self):
        resources = [{'Name': 'alias/aws/s3'}, {'Name': 'alias/app', 'TargetKeyId': 'abc'}]

        def has_target_key(manager, resource):
            return 'TargetKeyId' in resource

        self.assertEqual(
            FilterResources(has_target_key)(None, resources),
            [{'Name': 'alias/app', 'TargetKeyId': 'abc'}])

    def test_annotate_parent(self):
        resources = [('db1', {'Name': 'table1'})]

        self.assertEqual(
            AnnotateParent('DatabaseName')(None, resources),
            [{'Name': 'table1', 'DatabaseName': 'db1'}])

    def test_mutate_resource(self):
        resources = [{'Name': 'resource'}]

        def mark_seen(manager, resource):
            resource.update({'Seen': True})

        self.assertIs(
            MutateResource(mark_seen)(None, resources),
            resources)
        self.assertEqual(resources, [{'Name': 'resource', 'Seen': True}])

    def test_map_resource(self):
        def expand_odd(manager, resource):
            if resource % 2 == 0:
                return None
            return {'Value': resource}

        self.assertEqual(
            MapResource(expand_odd)(None, [1, 2, 3]),
            [{'Value': 1}, {'Value': 3}])

    def test_map_resource_uses_executor(self):
        class Executor:
            def __init__(self, max_workers):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def map(self, func, resources):
                return map(func, resources)

        class Manager:
            def __init__(self):
                self.workers = []

            def executor_factory(self, max_workers):
                self.workers.append(max_workers)
                return Executor(max_workers)

        manager = Manager()

        def expand_odd(manager, resource):
            if resource % 2 == 0:
                return None
            return {'Value': resource}

        self.assertEqual(
            MapResource(expand_odd, max_workers=2)(manager, [1, 2, 3]),
            [{'Value': 1}, {'Value': 3}])
        self.assertEqual(manager.workers, [2])

    def test_map_batch(self):
        seen = []

        def expand_batch(manager, resource_set):
            seen.append(list(resource_set))
            return [{'Value': r} for r in resource_set if r % 2]

        self.assertEqual(
            MapBatch(expand_batch, size=2)(None, [1, 2, 3]),
            [{'Value': 1}, {'Value': 3}])
        self.assertEqual(seen, [[1, 2], [3]])

    def test_map_batch_uses_executor(self):
        class Executor:
            def __init__(self, max_workers):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

            def map(self, func, resource_sets):
                return map(func, resource_sets)

        class Manager:
            def __init__(self):
                self.workers = []

            def executor_factory(self, max_workers):
                self.workers.append(max_workers)
                return Executor(max_workers)

        manager = Manager()

        def expand_batch(manager, resource_set):
            return [{'Value': r} for r in resource_set]

        self.assertEqual(
            MapBatch(expand_batch, size=2, max_workers=3)(
                manager, [1, 2, 3]),
            [{'Value': 1}, {'Value': 2}, {'Value': 3}])
        self.assertEqual(manager.workers, [3])

    def test_declarative_pipeline_composition_order(self):
        class Manager:
            parent_annotation = 'Parent'
            merge_field = 'Nested'

            @augment.filter
            def keep_resource(manager, resource):
                return resource.get('Keep')

            @augment.mutate
            def mark_seen(manager, resource):
                resource['Seen'] = resource['Parent']

        resources = [
            ('parent-a', {'Nested': {'Keep': True}}),
            ('parent-b', {'Nested': {'Keep': False}})]

        self.assertEqual(
            apply_augment_pipeline(Manager(), resources),
            [{'Parent': 'parent-a', 'Keep': True, 'Seen': 'parent-a'}])

    def test_declarative_pre_augment_filter(self):
        class Source:
            manager = object()

            @augment.pre_filter
            def keep_resource(manager, resource):
                return resource.get('Keep')

        resources = [{'Name': 'keep', 'Keep': True}, {'Name': 'drop'}]

        self.assertEqual(
            apply_source_augment_pipeline(Source(), resources, phase='pre'),
            [{'Name': 'keep', 'Keep': True}])

    def test_declarative_source_batch_uses_source_context(self):
        seen = []

        class Source:
            manager = object()

            @augment.source_batch(size=2)
            def expand_batch(source, resource_set):
                seen.append((source, list(resource_set)))
                return [{'Value': r} for r in resource_set if r % 2]

        source = Source()

        self.assertEqual(
            apply_source_augment_pipeline(source, [1, 2, 3]),
            [{'Value': 1}, {'Value': 3}])
        self.assertEqual(seen, [(source, [1, 2]), (source, [3])])

    def test_declarative_pipeline_runs_before_tags(self):
        class Manager:
            merge_field = 'Metadata'
            tag_field = dict(field='tags', remove=True, missing='empty')

        resources = [{'Metadata': {'tags': {'Owner': 'Policy'}}}]
        resources = apply_augment_pipeline(Manager(), resources)

        self.assertEqual(
            apply_tag_augment(Manager(), resources),
            [{'Tags': [{'Key': 'Owner', 'Value': 'Policy'}]}])


class QueryResourceManagerTest(BaseTest):

    def test_registries(self):
        self.assertTrue(InternetGateway.filter_registry)
        self.assertTrue(InternetGateway.action_registry)

    def test_resources(self):
        session_factory = self.replay_flight_data("test_query_manager")
        p = self.load_policy(
            {
                "name": "igw-check",
                "resource": "internet-gateway",
                "filters": [{"InternetGatewayId": "igw-2e65104a"}],
            },
            session_factory=session_factory,
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)

        output = self.capture_logging(
            name=p.resource_manager.log.name, level=logging.DEBUG
        )
        p.run()
        self.assertTrue("Using cached internet-gateway: 3", output.getvalue())

    def test_get_resources(self):
        session_factory = self.replay_flight_data("test_query_manager_get")
        p = self.load_policy(
            {"name": "igw-check", "resource": "internet-gateway"},
            session_factory=session_factory,
        )
        resources = p.resource_manager.get_resources(["igw-2e65104a"])
        self.assertEqual(len(resources), 1)
        resources = p.resource_manager.get_resources(["igw-5bce113f"])
        self.assertEqual(resources, [])

    def test_detail_spec_resource_not_found(self):
        # Test the case where List* API returns a resource that
        # is not found with the Get* API.

        # This test case has two CoreNetworks returned by the ListCoreNetworks API
        # but only one of them is found by the GetCoreNetwork API, since one is a Shared
        # resource from RAM and returns a 404.
        # So the policy should return only 1 CoreNetwork and log a message
        session_factory = self.replay_flight_data("test_networkmanager_core_networks_not_found")
        p = self.load_policy(
            {
                "name": "list-core-networks-not-found",
                "resource": "networkmanager-core",
            },
            session_factory=session_factory,
        )
        # Capture logging to check the output
        output = self.capture_logging(
            name=p.resource_manager.log.name, level=logging.WARNING
        )
        resources = p.run()
        self.assertEqual(len(resources), 1)

        for r in resources:
            self.assertTrue(r["CoreNetworkArn"])
            self.assertTrue("Segments" in r)
            self.assertTrue("Edges" in r)

        # Check that the warning message was logged
        self.assertTrue("Resource not found: get_core_network using" in output.getvalue())
        self.assertTrue(resources[0]["CoreNetworkArn"] not in output.getvalue())
