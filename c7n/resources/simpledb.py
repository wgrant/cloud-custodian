# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.actions import Action
from c7n.manager import resources
from c7n.query import QueryResourceManager, TypeInfo
from c7n.utils import local_session, type_schema


@resources.register('simpledb')
class SimpleDB(QueryResourceManager):

    class resource_type(TypeInfo):
        service = "sdb"
        enum_spec = ("list_domains", "DomainNames", None)
        id = name = "DomainName"
        arn_type = "domain"

    permissions = ('sdb:DomainMetadata',)

    @staticmethod
    def describe_domain_set(manager, resource_set):
        client = local_session(manager.session_factory).client('sdb')
        results = []
        for r in resource_set:
            info = client.domain_metadata(DomainName=r)
            info.pop('ResponseMetadata')
            info['DomainName'] = r
            results.append(info)
        return results

    augment_batcher = describe_domain_set

    augment_batch_size = 20
    augment_max_workers = 3


@SimpleDB.action_registry.register('delete')
class Delete(Action):

    schema = type_schema('delete')
    permissions = ('sdb:DeleteDomain',)

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('sdb')
        for r in resources:
            client.delete_domain(DomainName=r['DomainName'])
