# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

import logging

from c7n.manager import resources
from c7n.query import ConfigSource, QueryResourceManager, TagsFromApi, TypeInfo
from c7n import utils
from c7n import tags
from c7n.utils import local_session, type_schema
from c7n.actions import BaseAction

log = logging.getLogger('custodian.elasticbeanstalk')


@resources.register('elasticbeanstalk')
class ElasticBeanstalk(QueryResourceManager):

    class resource_type(TypeInfo):
        service = 'elasticbeanstalk'
        enum_spec = ('describe_applications', 'Applications', None)
        name = "ApplicationName"
        id = "ApplicationName"
        arn = "ApplicationArn"
        arn_type = 'application'
        default_report_fields = (
            'ApplicationName',
            'DateCreated',
            'DateUpdated'
        )
        filter_name = 'ApplicationNames'
        filter_type = 'list'
        cfn_type = config_type = 'AWS::ElasticBeanstalk::Application'
        permissions_augment = ("elasticbeanstalk:ListTagsForResource",)


@resources.register('elasticbeanstalk-environment')
class ElasticBeanstalkEnvironment(QueryResourceManager):
    """ Resource manager for Elasticbeanstalk Environments
    """

    class resource_type(TypeInfo):
        service = 'elasticbeanstalk'
        enum_spec = ('describe_environments', 'Environments', None)
        name = id = "EnvironmentName"
        arn = "EnvironmentArn"
        arn_type = 'environment'
        default_report_fields = (
            'EnvironmentName',
            'DateCreated',
            'DateUpdated',
        )
        filter_name = 'EnvironmentNames'
        filter_type = 'list'
        cfn_type = config_type = 'AWS::ElasticBeanstalk::Environment'
        permissions_augment = ("elasticbeanstalk:ListTagsForResource",)

    permissions = ('elasticbeanstalk:ListTagsForResource',)
    tag_augment = TagsFromApi(
        resource_path='EnvironmentArn',
        result_path='ResourceTags',
        ignore_errors=('ResourceNotFoundException',))
    source_mapping = {
        'config': ConfigSource
    }


ElasticBeanstalkEnvironment.filter_registry.register(
    'tag-count', tags.TagCountFilter)
ElasticBeanstalkEnvironment.filter_registry.register(
    'marked-for-op', tags.TagActionFilter)


@ElasticBeanstalkEnvironment.action_registry.register('mark-for-op')
class TagDelayedAction(tags.TagDelayedAction):
    """Mark an ElasticBeanstalk Environment for specific custodian action

    Note that this will cause an update to the environment to deploy the tag
    changes to all resources.

    :example:

    .. code-block:: yaml

            policies:
              - name: eb-mark-for-delete
                resource: elasticbeanstalk-environment
                filters:
                  - type: value
                    key: CNAME
                    op: regex
                    value: .*inactive.*
                actions:
                  - type: mark-for-op
                    op: terminate
                    days: 7
    """


@ElasticBeanstalkEnvironment.action_registry.register('tag')
class Tag(tags.Tag):
    """Tag an ElasticBeanstalk Environment with a key/value

    Note that this will cause an update to the environment to deploy the tag
    changes to all resources.

    :example:

    .. code-block:: yaml

            policies:
              - name: eb-env-tag-owner-tag
                resource: elasticbeanstalk-environment
                filters:
                  - "tag:OwnerName": absent
                actions:
                  - type: tag
                    key: OwnerName
                    value: OwnerName
    """

    batch_size = 5
    permissions = ('elasticbeanstalk:AddTags',)

    def process_resource_set(self, client, envs, ts):
        for env in envs:
            client.update_tags_for_resource(
                ResourceArn=env['EnvironmentArn'],
                TagsToAdd=ts)


@ElasticBeanstalkEnvironment.action_registry.register('remove-tag')
class RemoveTag(tags.RemoveTag):
    """Removes a tag or set of tags from ElasticBeanstalk Environments

    Note that this will cause an update to the environment to deploy the tag
    changes to all resources.

    :example:

    .. code-block:: yaml

            policies:
              - name: eb-env-unmark
                resource: elasticbeanstalk-environment
                filters:
                  - "tag:ExpiredTag": present
                actions:
                  - type: remove-tag
                    tags: ["ExpiredTag"]
    """

    batch_size = 5
    permissions = ('elasticbeanstalk:RemoveTags',)

    def process_resource_set(self, client, envs, tag_keys):
        for env in envs:
            client.update_tags_for_resource(
                ResourceArn=env['EnvironmentArn'],
                TagsToRemove=tag_keys)


@ElasticBeanstalkEnvironment.action_registry.register('terminate')
class Terminate(BaseAction):
    """ Terminate an ElasticBeanstalk Environment.

    :Example:

    .. code-block:: yaml

        policies:
          - name: eb-env-termination
            resource: elasticbeanstalk-environment
            filters:
              - type: marked-for-op
                op: terminate
            actions:
              - terminate
    """

    schema = type_schema(
        'terminate',
        force={'type': 'boolean', 'default': False},
        terminate_resources={'type': 'boolean', 'default': True}
    )
    permissions = ("elasticbeanstalk:TerminateEnvironment",)

    def process(self, envs):
        force_terminate = self.data.get('force', False)
        terminate_resources = self.data.get('terminate_resources', True)
        client = utils.local_session(
            self.manager.session_factory).client('elasticbeanstalk')
        for e in envs:
            client.terminate_environment(
                EnvironmentName=e["EnvironmentName"],
                TerminateResources=terminate_resources,
                ForceTerminate=force_terminate
            )
