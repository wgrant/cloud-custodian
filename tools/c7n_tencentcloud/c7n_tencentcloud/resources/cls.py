# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from c7n.query import augment
from c7n_tencentcloud.provider import resources
from c7n_tencentcloud.query import ResourceTypeInfo, QueryResourceManager, DescribeSource
from c7n_tencentcloud.utils import PageMethod


class LogGroupDescribe(DescribeSource):
    tag_augment = False

    @augment.mutate
    def set_uin(manager, resource):
        resource["c7n:uin"] = manager.config.account_id



@resources.register("cls")
class LogTopic(QueryResourceManager):
    """
    CLS - Cloud Log Service (CLS) is a centralized logging solution
    https://www.tencentcloud.com/document/product/614/11254?lang=en&pg=

    :example:

    .. code-block:: yaml

        policies:
        - name: tencentcloud-cls
          resource: tencentcloud.cls
          filters:
            - or:
              - "Period": 7
              - "Period": 3600
              - "Period": None
    """

    class resource_type(ResourceTypeInfo):
        """resource_type"""
        id = "TopicId"
        endpoint = "cls.tencentcloudapi.com"
        service = "cls"
        version = "2020-10-16"
        enum_spec = ("DescribeTopics", "Response.Topics[]", {})
        paging_def = {"method": PageMethod.Offset, "limit": {"key": "Limit", "value": 20}}
        resource_prefix = "topic"
        taggable = True
        metrics_enabled = True
        metrics_dimension_def = [("uin", "c7n:uin"), ("TopicId", "TopicId")]
        metrics_instance_id_name = "TopicId"
        metrics_namespace = "QCE/CLS"

    source_mapping = {'describe': LogGroupDescribe}
