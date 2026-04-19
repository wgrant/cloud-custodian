# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n_azure.resources.policy_assignments import PolicyAssignments

from ..azure_common import BaseTest


class PolicyAssignmentTest(BaseTest):

    def test_policy_assignment_schema_validate(self):
        with self.sign_out_patch():
            p = self.load_policy({
                'name': 'test-policy-assignment',
                'resource': 'azure.policyassignments'
            }, validate=True)
            self.assertTrue(p)

    def test_extra_args_uses_at_exact_scope_filter(self):
        # Without this filter, policy_assignments.list() returns assignments
        # inherited from parent management groups and the tenant root, which
        # would duplicate the same assignment across every subscription during
        # an org-wide inventory sync.
        self.assertEqual(
            PolicyAssignments.resource_type.extra_args(None),
            {'filter': 'atExactScope()'},
        )

    # run ./templates/provision.sh policyassignment to deploy required resource.
    def test_find_by_name(self):
        p = self.load_policy({
            'name': 'test-azure-public-ip',
            'resource': 'azure.policyassignments',
            'filters': [
                {'type': 'value',
                 'key': 'name',
                 'op': 'eq',
                 'value_type': 'normalize',
                 'value': 'cctestpolicy'}],
        })
        resources = p.run()
        self.assertEqual(len(resources), 1)
