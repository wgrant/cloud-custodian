# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.manager import resources
from c7n.filters.kms import KmsRelatedFilter
from c7n.query import QueryResourceManager, TypeInfo, DescribeSource, ConfigSource
from c7n.tags import universal_augment
from c7n.utils import local_session


class DescribeBackup(DescribeSource):

    @staticmethod
    def get_spec_postprocess(result):
        plan = result.pop('BackupPlan', {})
        result.update(plan)
        return result

    def augment(self, resources):
        resources = super(DescribeBackup, self).augment(resources)
        client = local_session(self.manager.session_factory).client('backup')
        results = []
        for r in resources:
            plan = r.pop('BackupPlan', {})
            r.update(plan)
            try:
                tags = client.list_tags(ResourceArn=r['BackupPlanArn']).get('Tags', {})
            except client.exceptions.ResourceNotFoundException:
                continue
            r['Tags'] = [{'Key': k, 'Value': v} for k, v in tags.items()]
            results.append(r)
        return results


@resources.register('backup-plan')
class BackupPlan(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'backup'
        enum_spec = ('list_backup_plans', 'BackupPlansList', None)
        detail_spec = ('get_backup_plan', 'BackupPlanId', 'BackupPlanId', None)
        id = 'BackupPlanName'
        name = 'BackupPlanId'
        arn = 'BackupPlanArn'
        config_type = cfn_type = 'AWS::Backup::BackupPlan'
        universal_taggable = object()
        permissions_augment = ("backup:ListTags",)

    source_mapping = {
        'describe': DescribeBackup,
        'config': ConfigSource
    }


class DescribeVault(DescribeSource):

    def augment(self, resources):
        return universal_augment(self.manager, super(DescribeVault, self).augment(resources))


@resources.register('backup-vault')
class BackupVault(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'backup'
        enum_spec = ('list_backup_vaults', 'BackupVaultList', None)
        get_spec = ('describe_backup_vault', 'BackupVaultName', None)
        name = id = 'BackupVaultName'
        arn = 'BackupVaultArn'
        arn_type = 'backup-vault'
        universal_taggable = object()
        config_type = cfn_type = 'AWS::Backup::BackupVault'

    source_mapping = {
        'describe': DescribeVault,
        'config': ConfigSource
    }


@BackupVault.filter_registry.register('kms-key')
class KmsFilter(KmsRelatedFilter):

    RelatedIdsExpression = 'EncryptionKeyArn'
