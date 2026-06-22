# Copyright The Cloud Custodian Authors.
# SPDX-License-Identifier: Apache-2.0
from c7n.manager import resources
from c7n import query


@resources.register("budget")
class Budget(query.QueryResourceManager):
    source_query_default = {"AccountId": query.source_account_id}

    class resource_type(query.TypeInfo):
        service = "budgets"
        enum_spec = ('describe_budgets', 'Budgets', None)
        global_resource = True
        arn_type = "budget"
        id = "BudgetName"
        name = "BudgetName"
        cfn_type = "AWS::Budgets::Budget"
        permissions_enum = ["budgets:ViewBudget"]
