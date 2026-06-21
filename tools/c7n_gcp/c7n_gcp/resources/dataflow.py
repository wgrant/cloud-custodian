# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.query import augment
from googleapiclient.errors import HttpError

from c7n_gcp.provider import resources
from c7n_gcp.query import QueryResourceManager, TypeInfo
from c7n.utils import jmespath_search


@resources.register('dataflow-job')
class DataflowJob(QueryResourceManager):
    """GCP resource: https://cloud.google.com/dataflow/docs/reference/rest/v1b3/projects.jobs
    """

    class resource_type(TypeInfo):
        service = 'dataflow'
        version = 'v1b3'
        component = 'projects.jobs'
        enum_spec = ('aggregated', 'jobs[]', None)
        scope_key = 'projectId'
        name = id = 'name'
        get_requires_event = True
        default_report_fields = [
            'name', 'currentState', 'createTime', 'location']
        permissions = ('dataflow.jobs.list',)
        urn_component = "job"
        urn_region_key = 'location'
        asset_type = "dataflow.googleapis.com/Job"

        @staticmethod
        def get(client, event):
            return client.execute_command(
                'get', {
                    'projectId': jmespath_search('resource.labels.project_id', event),
                    'jobId': jmespath_search('protoPayload.request.job_id', event)
                }
            )

    def prepare_query(self, query):
        query_filter = 'ACTIVE'
        if self.data.get('query'):
            query_filter = self.data['query'][0].get('filter', 'ACTIVE')

        return super().prepare_query({'filter': query_filter})

    @augment.map
    def describe_job(manager, resource):
        ref = {
            'jobId': resource['id'],
            'projectId': resource['projectId'],
            'view': 'JOB_VIEW_ALL'
        }
        try:
            return manager.get_client().execute_query(
                'get', verb_arguments=ref)
        except HttpError:
            return resource
