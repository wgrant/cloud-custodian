# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
#
from c7n.query import augment
from c7n_openstack.query import QueryResourceManager, TypeInfo, DescribeSource
from c7n_openstack.provider import resources
from c7n.utils import local_session


class StorageContainerMeta(DescribeSource):

    @augment.map
    def get_container_metadata(manager, resource):
        client = local_session(manager.session_factory).client()
        container_metadata = client.object_store.get_container_metadata(
            resource['name']).toDict()
        return container_metadata or None



@resources.register('storage-container')
class StorageContainer(QueryResourceManager):

    source_mapping = {'describe-openstack': StorageContainerMeta}

    class resource_type(TypeInfo):
        enum_spec = (['object_store', 'containers'], None)
        id = name = 'name'
        default_report_fields = ['name']
