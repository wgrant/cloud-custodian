# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
import pytz
from c7n_tencentcloud.provider import resources
from c7n_tencentcloud.query import NormalizeDateField, ResourceTypeInfo, QueryResourceManager
from c7n_tencentcloud.utils import PageMethod


@resources.register("nat-gateway")
class NatGateway(QueryResourceManager):
    """nat-gateway

    Docs on Nat Gateway
    https://www.tencentcloud.com/document/product/1015

    :example:

    .. code-block:: yaml

        policies:
          - name: nat-gateway-with-metrics-filter
            resource: tencentcloud.nat-gateway
            filters:
            - type: value
              key: CreatedTime
              value_type: age
              op: greater-than
              value: 7
            - type: metrics
              name: Conns
              statistics: Maximum
              days: 7
              value: 0
              missing-value: 0
              op: equal
              period: 3600
    """

    class resource_type(ResourceTypeInfo):
        """resource_type"""
        id = "NatGatewayId"
        endpoint = "vpc.tencentcloudapi.com"
        service = "vpc"
        version = "2017-03-12"
        enum_spec = ("DescribeNatGateways", "Response.NatGatewaySet[]", {})
        metrics_enabled = True
        metrics_namespace = "QCE/NAT_GATEWAY"
        metrics_dimension_def = [("natId", "NatGatewayId")]
        metrics_instance_id_name = "natId"
        paging_def = {"method": PageMethod.Offset, "limit": {"key": "Limit", "value": 20}}
        resource_prefix = "nat"
        taggable = True
        datetime_fields_format = {
            "CreatedTime": ("%Y-%m-%d %H:%M:%S", pytz.timezone("Asia/Shanghai"))
        }

    augment_pipeline = NormalizeDateField("CreatedTime")
