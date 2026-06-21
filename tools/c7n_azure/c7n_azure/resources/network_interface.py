# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0

from c7n_azure import constants
from c7n_azure.provider import resources
from c7n_azure.resources.arm import ArmResourceManager

from c7n.filters.core import BatchFilter, ValueFilter, type_schema
import logging

max_workers = constants.DEFAULT_MAX_THREAD_WORKERS
chunk_size = constants.DEFAULT_CHUNK_SIZE
log = logging.getLogger('custodian.azure.networkinterface')


@resources.register('networkinterface')
class NetworkInterface(ArmResourceManager):
    """Network Interface Resource

    :example:

    This policy will get Network Interfaces that have `User` added routes.

    .. code-block:: yaml

        policies:
          - name: get-nic-with-user-routes
            resource: azure.networkinterface
            filters:
              - type: effective-route-table
                key: routes.value[].source
                op: in
                value_type: swap
                value: User

    """

    class resource_type(ArmResourceManager.resource_type):
        doc_groups = ['Networking']

        service = 'azure.mgmt.network'
        client = 'NetworkManagementClient'
        enum_spec = ('network_interfaces', 'list_all', None)
        resource_type = 'Microsoft.Network/networkInterfaces'


@NetworkInterface.filter_registry.register('effective-route-table')
class EffectiveRouteTableFilter(BatchFilter, ValueFilter):
    """Filters network interfaces by the Effective Route Table

    :example:

    This policy will get Network Interfaces that have VirtualNetworkGateway and VNet hops.

    .. code-block:: yaml

        policies:
          - name: virtual-network-gateway-hop
            resource: azure.networkinterface
            filters:
              - type: effective-route-table
                key: routes.value[?source == 'User'].nextHopType
                op: difference
                value:
                  - Internet
                  - None
                  - VirtualAppliance
    """
    schema = type_schema('effective-route-table', rinherit=ValueFilter.schema)
    batch_size = chunk_size
    max_workers = max_workers

    @staticmethod
    def filter_resource_set(resource_filter, resources, event=None):
        client = resource_filter.manager.get_client()
        matched = []

        for resource in resources:
            try:
                if 'routes' not in resource:
                    rg = resource['resourceGroup']
                    route_table = (
                        client.network_interfaces
                        .begin_get_effective_route_table(rg, resource['name'])
                        .result()
                    )

                    resource['routes'] = route_table.serialize()
                    filtered_effective_route_table = ValueFilter.process(
                        resource_filter, [resource], event)

                    if filtered_effective_route_table:
                        matched.append(resource)

            except Exception as error:
                log.warning(error)

        return matched
