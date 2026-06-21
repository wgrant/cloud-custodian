# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.actions import Action
from c7n.filters.iamaccess import CrossAccountAccessFilter
from c7n.manager import resources
from c7n.resources.aws import Arn
from c7n.query import (
    MutateResource, QueryResourceManager, TypeInfo, DescribeSource, UniversalTags)
from c7n.utils import local_session, type_schema
from c7n.actions import BaseAction


class AccessPointDescribe(DescribeSource):
    @staticmethod
    def augment_access_point(manager, resource):
        client = local_session(manager.session_factory).client('s3control')
        arn = Arn.parse(resource['AccessPointArn'])
        details = manager.retry(
            client.get_access_point,
            AccountId=arn.account_id,
            Name=resource['Name'])
        details.pop('ResponseMetadata', None)
        details['AccessPointArn'] = arn.arn
        resource.update(details)

    augment_mutator = augment_access_point

    def get_query_params(self, query_params):
        query_params = query_params or {}
        query_params['AccountId'] = self.manager.config.account_id
        return query_params


@resources.register('s3-access-point')
class AccessPoint(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 's3control'
        id = name = 'Name'
        enum_spec = ('list_access_points', 'AccessPointList', None)
        arn = 'AccessPointArn'
        arn_service = 's3'
        arn_type = 'accesspoint'
        config_type = cfn_type = 'AWS::S3::AccessPoint'
        permission_prefix = 's3'

    source_mapping = {'describe': AccessPointDescribe}


@AccessPoint.filter_registry.register('cross-account')
class AccessPointCrossAccount(CrossAccountAccessFilter):

    policy_attribute = 'c7n:Policy'
    permissions = ('s3:GetAccessPointPolicy',)

    def process(self, resources, event=None):
        client = local_session(self.manager.session_factory).client('s3control')
        for r in resources:
            if self.policy_attribute in r:
                continue
            arn = Arn.parse(r['AccessPointArn'])
            resp = self.manager.retry(
                client.get_access_point_policy,
                AccountId=arn.account_id, Name=r['Name'],
                ignore_err_codes=('NoSuchAccessPointPolicy',),
            )
            r[self.policy_attribute] = resp.get('Policy') if resp else None

        return super().process(resources, event)


@AccessPoint.action_registry.register('delete')
class Delete(Action):

    schema = type_schema('delete')
    permissions = ('s3:DeleteAccessPoint',)

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('s3control')
        for r in resources:
            arn = Arn.parse(r['AccessPointArn'])
            try:
                client.delete_access_point(AccountId=arn.account_id, Name=r['Name'])
            except client.NotFoundException:
                continue


class MultiRegionAccessPointDescribe(DescribeSource):

    def get_query_params(self, query_params):
        query_params = query_params or {}
        query_params['AccountId'] = self.manager.config.account_id
        return query_params


@resources.register('s3-access-point-multi')
class MultiRegionAccessPoint(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 's3control'
        id = name = 'Name'
        enum_spec = ('list_multi_region_access_points', 'AccessPoints', None)
        arn_service = 's3'
        arn_type = 'accesspoint'
        config_type = cfn_type = 'AWS::S3::MultiRegionAccessPoint'
        permission_prefix = 's3'

    source_mapping = {'describe': MultiRegionAccessPointDescribe}


@MultiRegionAccessPoint.filter_registry.register('cross-account')
class MultiRegionAccessPointCrossAccount(CrossAccountAccessFilter):

    policy_attribute = 'c7n:Policy'
    permissions = ('s3:GetMultiRegionAccessPointPolicy',)

    def process(self, resources, event=None):
        client = local_session(self.manager.session_factory).client('s3control')
        for r in resources:
            if self.policy_attribute in r:
                continue
            r[self.policy_attribute] = self.manager.retry(
                client.get_multi_region_access_point_policy,
                AccountId=self.manager.config.account_id,
                Name=r['Name']
            ).get('Policy').get('Established').get('Policy')

        return super().process(resources, event)


class StorageLensDescribe(DescribeSource):
    @staticmethod
    def augment_storage_lens(manager, resource):
        client = local_session(manager.session_factory).client('s3control')
        resource.update(manager.retry(
            client.get_storage_lens_configuration,
            AccountId=manager.config.account_id,
            ConfigId=resource['Id']).get('StorageLensConfiguration'))

    augment_mutator = augment_storage_lens
    universal_tags = True

    def get_query_params(self, query_params):
        query_params = query_params or {}
        query_params['AccountId'] = self.manager.config.account_id
        return query_params


@resources.register('s3-storage-lens')
class StorageLens(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 's3control'
        id = name = 'Id'
        enum_spec = ('list_storage_lens_configurations', 'StorageLensConfigurationList', None)
        arn = 'StorageLensArn'
        arn_service = 's3'
        arn_type = 'storage-lens'
        cfn_type = 'AWS::S3::StorageLens'
        permission_prefix = 's3'
        universal_taggable = object()

    source_mapping = {'describe': StorageLensDescribe}


@StorageLens.action_registry.register('delete')
class DeleteStorageLens(BaseAction):
    """Delete a storage lens configuration

    :example:

    .. code-block:: yaml

        policies:
          - name: storage-lens-delete
            resource: aws.s3-storage-lens
            actions:
              - type: delete
    """
    schema = type_schema('delete')
    permissions = ('s3:DeleteStorageLensConfiguration',)

    def process(self, resources):
        client = local_session(self.manager.session_factory).client('s3control')
        accountId = self.manager.config.account_id
        for r in resources:
            configId = r['Id']
            client.delete_storage_lens_configuration(
                ConfigId=configId,
                AccountId=accountId
            )
