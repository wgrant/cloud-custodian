# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from c7n.manager import resources
from c7n.query import QueryResourceManager, TagAugmentSpec, TypeInfo


@resources.register('pinpoint-app')
class PinpointApp(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 'pinpoint'
        arn_type = 'apps'
        enum_spec = ('get_apps', 'ApplicationsResponse.Item', None)
        name = "Name"
        id = 'Id'
        universal_taggable = True
        cfn_type = 'AWS::Pinpoint::App'
        arn = "Arn"
        permission_prefix = 'mobiletargeting'
    tag_normalize = TagAugmentSpec(source='tags', default=())
