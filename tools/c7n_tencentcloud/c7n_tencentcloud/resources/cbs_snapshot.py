# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import pytz
from c7n_tencentcloud.provider import resources
from c7n_tencentcloud.query import NormalizeDateField, ResourceTypeInfo, QueryResourceManager
from c7n_tencentcloud.utils import PageMethod


@resources.register("cbs-snapshot")
class CBSSnapshot(QueryResourceManager):
    """cbs-snapshot

    Docs on cbs-snapshot
    https://www.tencentcloud.com/document/product/362/31638

    :example:

    .. code-block:: yaml

        policies:
        - name: cbs-old-snapshot
          resource: tencentcloud.cbs-snapshot
          filters:
            - type: value
              key: CreateTime
              value_type: age
              op: greater-than
              value: 90
    """

    class resource_type(ResourceTypeInfo):
        """resource_type"""
        id = "SnapshotId"
        endpoint = "cbs.tencentcloudapi.com"
        service = "cbs"
        version = "2017-03-12"
        enum_spec = ("DescribeSnapshots", "Response.SnapshotSet[]", {})
        paging_def = {"method": PageMethod.Offset, "limit": {"key": "Limit", "value": 20}}
        resource_prefix = "volume"
        taggable = True
        datetime_fields_format = {
            "CreateTime": ("%Y-%m-%d %H:%M:%S", pytz.timezone("Asia/Shanghai"))
        }

    augment_pipeline = NormalizeDateField("CreateTime")
