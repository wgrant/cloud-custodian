# Cloud Custodian Architectural Analysis: AWS vs Azure vs GCP

## Executive Summary

Cloud Custodian's architecture demonstrates significant evolution from the AWS core implementation to the newer Azure and GCP providers. The newer implementations show thoughtful improvements in declarative patterns, type system maturity, and provider-specific abstractions. This analysis identifies architectural patterns and recommends improvements to reduce duplication and improve maintainability in the AWS core.

---

## 1. RESOURCE MANAGER ARCHITECTURE

### 1.1 AWS Core Pattern: Imperative with Metadata Classes

**Location**: `/home/user/cloud-custodian/c7n/manager.py` (lines 32-154)
**Resource Examples**: `/home/user/cloud-custodian/c7n/resources/ec2.py`, `/home/user/cloud-custodian/c7n/resources/s3.py`

AWS uses a **complex nested metaclass hierarchy** with imperative registration:

```python
# AWS Core (manager.py:32-60)
class ResourceManager:
    filter_registry = None
    action_registry = None
    executor_factory = ThreadPoolExecutor
    
    def __init__(self, ctx, data):
        self.ctx = ctx
        self.session_factory = ctx.session_factory
        # Manual initialization of filters/actions
        if self.filter_registry:
            self.filters = self.filter_registry.parse(
                self.data.get('filters', []), self)
        if self.action_registry:
            self.actions = self.action_registry.parse(
                self.data.get('actions', []), self)

# Resource Type Metadata (ec2.py:114-142)
@resources.register('ec2')
class EC2(query.QueryResourceManager):
    class resource_type(query.TypeInfo):
        service = 'ec2'
        arn_type = 'instance'
        enum_spec = ('describe_instances', 'Reservations[].Instances[]', None)
        id = 'InstanceId'
        filter_name = 'InstanceIds'
        # 40+ lines of metadata
```

**Issues**:
- Verbose metadata specification with inconsistent naming
- Heavy reliance on inner classes and metaclasses
- Manual registry assignment in each resource file
- Scattered metadata across multiple levels

### 1.2 Azure Pattern: Declarative Metaclass with Automatic Registration

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/resources/arm.py` (lines 23-102)
**Resource Example**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/resources/disk.py` (lines 14-48)

Azure uses **cleaner metaclass magic with automatic registration**:

```python
# Azure TypeInfo (arm.py:23-33)
class ArmTypeInfo(TypeInfo, metaclass=TypeMeta):
    id = 'id'
    name = 'name'
    diagnostic_settings_enabled = True
    default_report_fields = (
        'name',
        'location',
        'resourceGroup'
    )
    resource_type = None  # Computed by metaclass

# Azure Resource Definition (disk.py:14-47)
@resources.register('disk')
class Disk(ArmResourceManager):
    """Disk Resource"""
    
    class resource_type(ArmResourceManager.resource_type):
        doc_groups = ['Storage']
        service = 'azure.mgmt.compute'
        client = 'ComputeManagementClient'
        enum_spec = ('disks', 'list', None)
        default_report_fields = (
            'name',
            'location',
            'resourceGroup',
            'properties.diskState',
            'sku.name'
        )
        resource_type = 'Microsoft.Compute/disks'
```

**Key Improvements**:
- Metaclass (`TypeMeta`) automatically wires filter/action registries
- Inheritance-based defaults reduce boilerplate
- Subscription-based pattern for resource registration (`resources.subscribe()`)

### 1.3 GCP Pattern: Minimal Metaclass with Clear Separation

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/query.py` (lines 360-509)
**Resource Example**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/resources/dataflow.py` (lines 10-44)

GCP shows **most explicit and least magical approach**:

```python
# GCP TypeInfo (query.py:360-390)
class TypeInfo(metaclass=TypeMeta):
    # api client construction information
    service = None
    version = None
    component = None
    
    # resource enumeration parameters
    scope = 'project'
    enum_spec = ('list', 'items[]', None)
    scope_key = None
    scope_template = None
    
    # individual resource retrieval
    get = None
    get_requires_event = False
    
    # required for reporting
    id = None
    name = None
    default_report_fields = ()
    
    # asset inventory type
    asset_type = None

# GCP Resource (dataflow.py:10-44)
@resources.register('dataflow-job')
class DataflowJob(QueryResourceManager):
    """GCP resource: https://cloud.google.com/dataflow/docs/reference/rest/v1b3/projects.jobs"""
    
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
```

**Characteristics**:
- Cleaner separation between service client construction and resource metadata
- Explicit typing (e.g., `urn_component`, `asset_type`)
- No implicit defaults inheritance - everything explicit

---

## 2. QUERY/FILTER PATTERNS

### 2.1 AWS: Heterogeneous Query Sources

**Location**: `/home/user/cloud-custodian/c7n/query.py` (lines 36-250)

AWS has multiple specialized query classes:

```python
# Base ResourceQuery (query.py:36-78)
class ResourceQuery:
    def filter(self, resource_manager, **params):
        """Query a set of resources."""
        # AWS-specific client invocation
        m = self.resolve(resource_manager.resource_type)
        client = local_session(self.session_factory).client(
            m.service, resource_manager.config.region)
        enum_op, path, extra_args = m.enum_spec
        return self._invoke_client_enum(
            client, enum_op, params, path,
            getattr(resource_manager, 'retry', None)) or []

# Child Resource Query (query.py:111-175)
class ChildResourceQuery(ResourceQuery):
    """A resource query for resources that must be queried with parent information.
    
    Several resource types can only be queried in the context of their
    parents identifiers. ie. efs mount targets (parent efs), route53 resource
    records (parent hosted zone), ecs services (ecs cluster).
    """
    
    parent_key = 'c7n:parent-id'
    
    def filter(self, resource_manager, parent_ids=None, **params):
        # Complex logic to handle parent relationships
        parent_type, parent_key, annotate_parent = m.parent_spec
        parents = self.manager.get_resource_manager(parent_type)
        # ... hierarchical query logic
```

**Challenges**:
- Ad-hoc query implementations scattered across resource files
- No standardized parent-child relationship mechanism
- Hard to trace query patterns across resources

### 2.2 Azure: Unified Resource Query

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/query.py` (lines 29-62)

Azure has a **single unified query approach**:

```python
# Azure ResourceQuery (query.py:29-69)
class ResourceQuery:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def filter(self, resource_manager, query=None, **params):
        m = resource_manager.resource_type
        enum_op, list_op, extra_args = m.enum_spec
        
        if extra_args:
            params.update(extra_args)
        
        params.update(m.extra_args(resource_manager))
        
        try:
            op = getattr(getattr(resource_manager.get_client(), enum_op), list_op)
            if query:
                params.update(**query[0])
            
            result = op(**params)
            
            if isinstance(result, Iterable):
                return [r.serialize(True) for r in result]
            elif hasattr(result, 'value'):
                return [r.serialize(True) for r in result.value]
```

**Advantages**:
- Single query path for all resources
- Handles iterable vs value properties uniformly
- `extra_args()` pattern for customization
- No special child resource query class

### 2.3 GCP: Source-Based Query Abstraction

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/query.py` (lines 22-137)

GCP uses **pluggable source patterns**:

```python
# GCP ResourceQuery (query.py:22-63)
class ResourceQuery:
    def filter(self, resource_manager, **params):
        m = resource_manager.resource_type
        session = local_session(self.session_factory)
        client = session.client(
            m.service, m.version, m.component)
        
        # Scope handling (project/zone/global)
        if m.scope in ('project', 'zone'):
            project = session.get_default_project()
            if m.scope_template:
                project = m.scope_template.format(project)
            if m.scope_key:
                params[m.scope_key] = project
            else:
                params['project'] = project
        
        if m.scope == 'zone':
            if session.get_default_zone():
                params['zone'] = session.get_default_zone()
        
        enum_op, path, extra_args = m.enum_spec
        if extra_args:
            params.update(extra_args)
        return self._invoke_client_enum(
            client, enum_op, params, path)

# Alternative Source: Asset Inventory (query.py:95-130)
@sources.register('inventory')
class AssetInventory:
    """Alternative query source using Cloud Asset Inventory"""
    
    permissions = ("cloudasset.assets.searchAllResources",
                   "cloudasset.assets.exportResource")
    
    def get_resources(self, query):
        session = local_session(self.manager.session_factory)
        # ... Cloud Asset API query logic
```

**Strengths**:
- Pluggable query sources (describe vs asset inventory)
- Clean scope template handling
- Extensible to alternative query mechanisms

### 2.4 Filter Registry Patterns

**AWS Filter Registry** (c7n/filters/core.py:117-170):
```python
class FilterRegistry(PluginRegistry):
    value_filter_class = None
    
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.register('value', ValueFilter)
        self.register('or', Or)
        self.register('and', And)
        self.register('not', Not)
        self.register('event', EventFilter)
        self.register('reduce', ReduceFilter)
        self.register('list-item', ListItemFilter)
    
    def factory(self, data, manager=None):
        """Factory func for filters with complex type checking"""
        if isinstance(data, dict) and len(data) == 1 and 'type' not in data:
            op = list(data.keys())[0]
            if op == 'or':
                return self['or'](data, self, manager)
            # ... complex syntactic sugar logic
```

**Azure Filter Registry** (c7n_azure/c7n_azure/filters.py):
- Simpler, inherits from c7n.filters.FilterRegistry
- Adds cloud-specific filters via decorator pattern
- Uses subscription pattern for auto-registration

**GCP Filter Registry** (c7n_gcp/c7n_gcp/query.py:139-150):
```python
class QueryMeta(type):
    """metaclass to have consistent action/filter registry for new resources."""
    def __new__(cls, name, parents, attrs):
        if 'filter_registry' not in attrs:
            attrs['filter_registry'] = FilterRegistry(
                '%s.filters' % name.lower())
        if 'action_registry' not in attrs:
            attrs['action_registry'] = ActionRegistry(
                '%s.actions' % name.lower())
        
        return super(QueryMeta, cls).__new__(cls, name, parents, attrs)
```

---

## 3. ACTION PATTERNS

### 3.1 AWS: Scattered Action Implementations

**Location**: `/home/user/cloud-custodian/c7n/actions/core.py` (lines 1-76)

AWS base action is minimal:

```python
class Action(Element):
    log = logging.getLogger("custodian.actions")
    
    def __init__(self, data=None, manager=None, log_dir=None):
        self.data = data or {}
        self.manager = manager
        self.log_dir = log_dir
    
    @property
    def name(self):
        return self.__class__.__name__.lower()
    
    def process(self, resources):
        raise NotImplementedError(
            "Base action class does not implement behavior")
    
    def _run_api(self, cmd, *args, **kw):
        try:
            return cmd(*args, **kw)
        except ClientError as e:
            if (e.response['Error']['Code'] == 'DryRunOperation' ...):
                return self.log.info(...)
            raise
```

- Actions scattered across `/home/user/cloud-custodian/c7n/actions/` (8 modules)
- No unified base for cloud operations
- DryRun logic buried in base class

### 3.2 Azure: Base Action with Threading

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/actions/base.py` (lines 1-75)

Azure provides a **rich base action class**:

```python
class AzureBaseAction(BaseAction, metaclass=abc.ABCMeta):
    session = None
    max_workers = constants.DEFAULT_MAX_THREAD_WORKERS
    chunk_size = constants.DEFAULT_CHUNK_SIZE
    log = logging.getLogger('custodian.azure.AzureBaseAction')
    
    def process(self, resources, event=None):
        self.session = self.manager.get_session()
        results, exceptions = self.process_in_parallel(resources, event)
        
        if len(exceptions) > 0:
            self.handle_exceptions(exceptions)
        
        return results
    
    def handle_exceptions(self, exceptions):
        """raising one exception re-raises the last exception and maintains
        the stack trace"""
        raise exceptions[0]
    
    def process_in_parallel(self, resources, event):
        return ThreadHelper.execute_in_parallel(
            resources=resources,
            event=event,
            execution_method=self._process_resources,
            executor_factory=self.executor_factory,
            log=self.log,
            max_workers=self.max_workers,
            chunk_size=self.chunk_size
        )
    
    def _process_resources(self, resources, event):
        self._prepare_processing()
        
        for r in resources:
            try:
                result = self._process_resource(r)
                self._log_modified_resource(r, result)
            except Exception as e:
                # error handling with metadata
```

**Advantages**:
- Standardized parallel processing pattern
- Automatic threading with configurable workers
- Consistent error handling and logging
- Built-in metadata collection for action auditing

### 3.3 GCP: Method-Based Action Pattern

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/actions/core.py`

GCP introduces a **declarative method-based action pattern**:

```python
class MethodAction(Action):
    """Action that invokes a GCP API method directly."""
    
    # Derived from resource metadata
    # Automatically builds the right API call based on resource type
```

This allows actions like:

```python
# Example from labels.py
@resource_class.action_registry.register('set-labels')
class SetLabelsAction(BaseLabelAction):
    """Set GCP labels on resources"""
    # Uses MethodAction to call setLabels API
```

**Pattern Advantage**: Reduces boilerplate for CRUD-like actions

---

## 4. PROVIDER INTEGRATION

### 4.1 AWS: Session Factory with Role Assumption

**Location**: `/home/user/cloud-custodian/c7n/credentials.py` (lines 1-60)

```python
class CustodianSession(Session):
    # track clients and return extant ones if present
    _clients = {}
    lock = threading.Lock()
    
    def client(self, service_name, region_name=None, *args, **kw):
        if kw.get('config'):
            return super().client(service_name, region_name, *args, **kw)
        
        key = self._cache_key(service_name, region_name)
        client = self._clients.get(key)
        if client is not None:
            return client
        
        with self.lock:
            client = self._clients.get(key)
            if client is not None:
                return client
            
            client = super().client(service_name, region_name, *args, **kw)
            self._clients[key] = client
            return client

class SessionFactory:
    def __init__(
            self, region, profile=None, assume_role=None, external_id=None, session_policy=None):
        self.region = region
        self.profile = profile
        self.session_policy = session_policy
        self.assume_role = assume_role
        self.external_id = external_id
        # ... role assumption logic
```

**Features**:
- Client caching with thread-safety
- Assume role support with external ID
- Session policy restrictions
- Region-scoped clients

### 4.2 Azure: Flexible Credential Management

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/session.py` (lines 1-80)

```python
class AzureCredential:
    def __init__(self, cloud_endpoints, authorization_file=None, subscription_id_override=None):
        if authorization_file:
            with open(authorization_file) as json_file:
                self._auth_params = json.load(json_file)
        else:
            self._auth_params = {
                'client_id': os.environ.get(constants.ENV_CLIENT_ID),
                'client_secret': os.environ.get(constants.ENV_CLIENT_SECRET),
                'access_token': os.environ.get(constants.ENV_ACCESS_TOKEN),
                'tenant_id': os.environ.get(constants.ENV_TENANT_ID),
                'use_msi': bool(os.environ.get(constants.ENV_USE_MSI)),
                'subscription_id': os.environ.get(constants.ENV_SUB_ID),
                'keyvault_client_id': os.environ.get(constants.ENV_KEYVAULT_CLIENT_ID),
                'keyvault_secret_id': os.environ.get(constants.ENV_KEYVAULT_SECRET_ID),
                'client_certificate_path': os.environ.get(constants.ENV_CLIENT_CERTIFICATE_PATH),
                'client_certificate_password': os.environ.get(constants.ENV_CLIENT_CERTIFICATE_PASSWORD),
                'enable_cli_auth': True
            }
```

**Unique Features**:
- Multiple auth strategies (env, file, CLI, MSI, certificate)
- KeyVault integration for credential storage
- Cloud endpoint abstraction
- Subscription ID override support

### 4.3 GCP: Service Account and Impersonation

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/client.py` (lines 1-60)

```python
GOOGLE_IMPERSONATE_SERVICE_ACCOUNT = os.environ.get('GOOGLE_IMPERSONATE_SERVICE_ACCOUNT')

def get_default_project():
    for k in ('GCP_PROJECT', 'GOOGLE_PROJECT', 'GCLOUD_PROJECT',
              'GOOGLE_CLOUD_PROJECT', 'CLOUDSDK_CORE_PROJECT'):
        if k in os.environ:
            return os.environ[k]
```

**Features**:
- Service account impersonation
- Multiple environment variable conventions
- Rate limiting support (`pyrate_limiter`)
- HTTP retry logic (HTTP 503, connection errors)

---

## 5. TYPE SYSTEM & METADATA

### 5.1 AWS: Verbose TypeInfo with Many Optional Fields

**Location**: `/home/user/cloud-custodian/c7n/query.py` (lines 792-890)

AWS TypeInfo has extensive metadata (100+ lines):

```python
class TypeInfo(metaclass=TypeMeta):
    """Resource Type Metadata"""
    
    # Service & API info
    service: str
    enum_spec: tuple  # (operation, jmespath_path, extra_args)
    
    # Resource identification
    id: str
    name: str
    arn: Optional[str]
    arn_type: str
    arn_separator: str
    
    # Filtering for get operations
    filter_name: str
    filter_type: str  # 'list' or 'scalar'
    
    # Permissions
    permission_prefix: Optional[str]
    permissions_enum: tuple
    permissions_augment: tuple
    
    # Configuration Management
    config_type: str  # AWS Config type
    cfn_type: str  # CloudFormation type
    
    # Reporting & Tagging
    dimension: str  # CloudWatch dimension
    universal_taggable: bool
    taggable: bool
    default_report_fields: tuple
    
    # Parent-child relationships
    parent_spec: Optional[tuple]
    
    # And many more...
```

**Challenges**:
- Overwhelming number of optional metadata fields
- Inconsistent naming conventions
- Scattered documentation
- No enforcement of required fields

### 5.2 Azure: Minimal Focused Metadata

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/query.py` (lines 181-212)

Azure has **cleaner metadata**:

```python
class TypeInfo(metaclass=TypeMeta):
    doc_groups = None
    
    """api client construction information"""
    service = ''
    client = ''
    
    resource = DEFAULT_RESOURCE_AUTH_ENDPOINT
    id = 'id'
    name = 'name'
    
    default_report_fields = ()
    
    @classmethod
    def extra_args(cls, resource_manager):
        return {}

class ChildTypeInfo(TypeInfo, metaclass=TypeMeta):
    """api client construction information for child resources"""
    parent_manager_name = ''
    annotate_parent = True
    raise_on_exception = True
    parent_key = 'c7n:parent-id'
    keyvault_child = False
    
    @classmethod
    def extra_args(cls, parent_resource):
        return {}
```

**Advantages**:
- Minimal required fields
- Clear separation of ARM-specific info
- Explicit parent-child patterns
- Method-based customization via `extra_args()`

### 5.3 GCP: Structured URN and Asset Metadata

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/query.py` (lines 360-480)

GCP has **focused metadata with URN generation**:

```python
class TypeInfo(metaclass=TypeMeta):
    # api client construction information
    service = None
    version = None
    component = None
    
    # resource enumeration parameters
    scope = 'project'
    enum_spec = ('list', 'items[]', None)
    scope_key = None
    scope_template = None
    
    # individual resource retrieval method
    get = None
    get_requires_event = False
    perm_service = None
    permissions = ()
    
    # labels support
    labels = False
    labels_op = 'setLabels'
    
    # required for reporting
    id = None
    name = None
    default_report_fields = ()
    
    # cloud asset inventory type
    asset_type = None
    
    # URN generation
    urn_region_key = 'region'
    urn_id_path = None
    urn_id_segments = None
    urn_component = None
    urn_has_project = True
    urn_zonal = False
    
    @classmethod
    def get_urns(cls, resources, project_id):
        """Generate URNs for resources following GCP URN format"""
        return [cls._get_urn(r, project_id) for r in resources]
    
    @classmethod
    def _get_urn(cls, resource, project_id) -> str:
        location = cls._get_location(resource)
        if location == "global":
            location = ""
        id = cls._get_urn_id(resource)
        if not cls.urn_has_project:
            project_id = ""
        return f"gcp:{cls.service}:{location}:{project_id}:{cls.urn_component}/{id}"
```

**Strengths**:
- Structured URN generation for unified identification
- Asset inventory integration
- Clean scope handling
- Explicit label support with operations

---

## 6. CODE ORGANIZATION & PLUGIN ARCHITECTURE

### 6.1 AWS: Distributed Resource Definitions

**Location**: `/home/user/cloud-custodian/c7n/resources/` (60+ resource files)

```
c7n/resources/
├── __init__.py (load_resources function)
├── asg.py
├── cfn.py
├── dynamodb.py
├── ec2.py
├── elb.py
├── iam.py
├── rds.py
├── s3.py
├── ... (40+ more resources)
```

**Pattern**:
```python
# Each resource file imports and registers itself
@resources.register('ec2')
class EC2(query.QueryResourceManager):
    class resource_type(query.TypeInfo):
        # metadata...

# Filters and actions registered locally
filters = FilterRegistry('ec2.filters')
actions = ActionRegistry('ec2.actions')

@filters.register('instance-state')
class InstanceStateFilter(Filter):
    pass

@actions.register('stop')
class StopInstances(BaseAction):
    pass
```

**Consequences**:
- 60+ separate registration points
- Hard to trace where filters/actions are defined
- Resource files are large (500+ lines each)
- No central registry of what's available

### 6.2 Azure: Centralized Resource Map

**Location**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/resources/resource_map.py`

Azure uses a **single resource map** that's generated:

```python
# (Implied structure)
ResourceMap = {
    'vm': 'c7n_azure.resources.vm:VirtualMachine',
    'disk': 'c7n_azure.resources.disk:Disk',
    'keyvault': 'c7n_azure.resources.keyvault:KeyVault',
    # ... all resources mapped
}
```

**Benefits**:
- Single point of truth for available resources
- Enables fast lookups
- Better for documentation and help systems
- Cleaner provider initialization

### 6.3 GCP: Resource Discovery Pattern

**Location**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/resources/`

GCP uses similar distributed pattern to AWS but with better organization:

```python
# Each resource is well-contained
@resources.register('instance')
class Instance(QueryResourceManager):
    class resource_type(TypeInfo):
        service = 'compute'
        version = 'v1'
        component = 'instances'
        # ... focused metadata
    
    # Few filters/actions defined here
    filter_registry.register('offhour', OffHour)
    filter_registry.register('onhour', OnHour)
```

### 6.4 Plugin Registry Pattern

All three clouds use the same **plugin registry mechanism**:

```python
class PluginRegistry:
    """A plugin registry - string to class map with entry_point loading"""
    
    def __init__(self, plugin_type):
        self.plugin_type = plugin_type
        self._factories = {}
        self._subscribers = []
    
    def register(self, name, klass=None, condition=True, ...):
        # Can be used as decorator or function
        
    def subscribe(self, func):
        # Subscriber pattern for side effects
        self._subscribers.append(func)
    
    def notify(self, key=None):
        # Trigger all subscribers when resource is registered
        for subscriber in self._subscribers:
            subscriber(self, key)
```

**Azure Enhancement**: Uses `subscribe` pattern for automatic filter/action registration:

```python
# In arm.py
@resources.subscribe(ArmResourceManager.register_arm_specific)
# This function automatically registers filters/actions for all ARM resources
def register_arm_specific(registry, resource_class):
    if ArmResourceManager.generic_resource_supports_tagging(...):
        resource_class.action_registry.register('tag', Tag)
        resource_class.action_registry.register('untag', RemoveTag)
        # ... auto-register common actions
```

---

## 7. ARCHITECTURAL IMPROVEMENTS & RECOMMENDATIONS

### 7.1 Recommendation 1: Adopt Azure's Metaclass Pattern for AWS

**Current State**: AWS uses verbose nested classes
**Target**: Use metaclass to auto-wire registries

```python
# Proposed AWS improvement
class QueryMeta(type):
    """Metaclass to auto-wire filter/action registries"""
    def __new__(cls, name, parents, attrs):
        if 'filter_registry' not in attrs:
            attrs['filter_registry'] = FilterRegistry(
                '%s.filters' % name.lower())
        if 'action_registry' not in attrs:
            attrs['action_registry'] = ActionRegistry(
                '%s.actions' % name.lower())
        return super(QueryMeta, cls).__new__(cls, name, parents, attrs)

# Usage becomes simpler
@resources.register('ec2')
class EC2(query.QueryResourceManager, metaclass=QueryMeta):
    class resource_type(query.TypeInfo):
        service = 'ec2'
        arn_type = 'instance'
        enum_spec = ('describe_instances', 'Reservations[].Instances[]', None)
        # Filters and actions are auto-registered!
```

**Impact**: 
- Reduces boilerplate in 60+ AWS resource files
- Prevents duplicate registry definitions
- File: `/home/user/cloud-custodian/c7n/query.py` (lines 200+)

### 7.2 Recommendation 2: Consolidate Query Patterns

**Current State**: AWS has ResourceQuery and ChildResourceQuery
**Target**: Use source pattern like GCP

```python
# Proposed AWS improvement - sources/describe.py
@sources.register('describe')
class DescribeSource:
    def __init__(self, manager):
        self.manager = manager
        self.query = ResourceQuery(manager.session_factory)
    
    def get_resources(self, query):
        return self.query.filter(self.manager, **query or {})

# For parent-child relationships
@sources.register('child')
class ChildSource:
    """Source for resources that require parent context"""
    
    def __init__(self, manager):
        self.manager = manager
        self.query = ChildResourceQuery(
            manager.session_factory, manager)
    
    def get_resources(self, query):
        parent_ids = query.get('parent_ids') if query else None
        return self.query.filter(self.manager, parent_ids=parent_ids)
```

**Benefits**:
- Single query point per resource
- Pluggable alternatives (e.g., AWS Config)
- Easier to test and understand
- File: `/home/user/cloud-custodian/c7n/query.py`

### 7.3 Recommendation 3: Extract Threading Pattern from Azure

**Current State**: AWS actions don't have built-in parallelization strategy
**Target**: Use Azure's ThreadHelper pattern

```python
# Proposed AWS improvement
from concurrent.futures import ThreadPoolExecutor
from c7n.utils import ThreadHelper

class BaseAction(Element):
    max_workers = 4
    chunk_size = 100
    
    def process(self, resources, event=None):
        """Process resources with automatic parallelization"""
        if len(resources) <= self.chunk_size:
            return self._process_resources(resources, event)
        
        return ThreadHelper.execute_in_parallel(
            resources=resources,
            event=event,
            execution_method=self._process_resources,
            executor_factory=self.executor_factory,
            log=self.log,
            max_workers=self.max_workers,
            chunk_size=self.chunk_size
        )
    
    def _process_resources(self, resources, event):
        """Override in subclass"""
        raise NotImplementedError()
```

**Benefits**:
- Consistent resource processing across all actions
- Built-in error handling and logging
- Reduces code duplication in S3, EC2, etc.
- File: `/home/user/cloud-custodian/c7n/actions/core.py`

### 7.4 Recommendation 4: Simplify TypeInfo Metadata

**Current State**: AWS TypeInfo has 50+ optional fields
**Target**: Create focused base classes by concern

```python
# Proposed AWS improvement
class BaseTypeInfo:
    """Minimal required metadata"""
    service: str
    enum_spec: tuple
    id: str
    name: str
    default_report_fields: tuple = ()

class TaggableTypeInfo(BaseTypeInfo):
    """For resources that support tagging"""
    taggable: bool = True
    universal_taggable: bool = False

class ArnTypeInfo(BaseTypeInfo):
    """For resources with ARNs"""
    arn: Optional[str] = None
    arn_type: str
    arn_separator: str = ':'

class ConfigTypeInfo(BaseTypeInfo):
    """For resources available in AWS Config"""
    config_type: str
    cfn_type: str

class RelationalTypeInfo(BaseTypeInfo):
    """For resources with parent-child relationships"""
    parent_spec: Optional[tuple] = None

# Usage
class EC2ResourceType(BaseTypeInfo, TaggableTypeInfo, ArnTypeInfo):
    service = 'ec2'
    arn_type = 'instance'
    # Only declare relevant fields!
```

**Benefits**:
- Metadata organized by concern
- Clear which fields are required per resource type
- Reduces cognitive load
- Better type safety

### 7.5 Recommendation 5: Adopt Subscription Pattern for Action/Filter Registration

**Current State**: Resources manually register filters/actions
**Target**: Use subscription pattern from Azure

```python
# Proposed AWS improvement
def register_universal_tags(registry, resource_class):
    """Subscribe to all QueryResourceManager classes"""
    if hasattr(resource_class, 'filter_registry'):
        resource_class.filter_registry.register('tag', ValueFilter)
        resource_class.action_registry.register('tag', Tag)
        resource_class.action_registry.register('untag', RemoveTag)

# In resources module
resources.subscribe(register_universal_tags)

# Also subscription for EC2-specific items
def register_ec2_specific(registry, resource_class):
    if getattr(resource_class, 'service', None) == 'ec2':
        resource_class.filter_registry.register('instance-state', InstanceStateFilter)
        resource_class.action_registry.register('stop', StopInstances)

resources.subscribe(register_ec2_specific)
```

**Benefits**:
- Centralized, declarative filter/action registration
- No need to import filters/actions in each resource file
- Easier to understand which filters/actions apply to which resources
- Better organization of shared patterns
- File: `/home/user/cloud-custodian/c7n/manager.py`

### 7.6 Recommendation 6: Unified Error Handling Across Clouds

**Current State**: Error handling differs by cloud
**Target**: Abstract error handling in base classes

```python
# Proposed improvement
from abc import ABC, abstractmethod

class CloudError(Exception):
    """Base cloud error"""
    def __init__(self, code, message, http_status=None):
        self.code = code
        self.message = message
        self.http_status = http_status
    
    @property
    def is_transient(self):
        """Whether error is retryable"""
        raise NotImplementedError()

class AWSError(CloudError):
    def __init__(self, client_error):
        super().__init__(
            code=client_error.response['Error']['Code'],
            message=client_error.response['Error']['Message'],
            http_status=client_error.response['ResponseMetadata']['HTTPStatusCode']
        )
    
    @property
    def is_transient(self):
        return self.code in ('ServiceUnavailable', 'ThrottlingException')

# In actions
def _run_api(self, cmd, *args, **kw):
    try:
        return cmd(*args, **kw)
    except ClientError as e:
        cloud_error = AWSError(e)
        if cloud_error.is_transient:
            self.log.warning(f"Transient error, will retry: {cloud_error.message}")
            # Retry logic
        else:
            raise
```

**Benefits**:
- Consistent error semantics across clouds
- Centralized retry logic
- Better error reporting

---

## 8. CODE DUPLICATION ANALYSIS

### 8.1 Filter Duplication

**Pattern Found**: Value filters, metric filters, tag filters are duplicated

**AWS**: `c7n/filters/core.py` (ValueFilter, 300+ lines)
**Azure**: `c7n_azure/c7n_azure/filters.py` (includes ValueFilter from c7n)
**GCP**: Inherits from `c7n.filters`

**Recommendation**: 
- Share ValueFilter implementation fully
- Create cloud-specific extensions for cloud-unique logic
- Example: Azure's MetricFilter is truly cloud-specific

### 8.2 Session/Credential Duplication

**AWS**: `/home/user/cloud-custodian/c7n/credentials.py` (SessionFactory, 100+ lines)
**Azure**: `/home/user/cloud-custodian/tools/c7n_azure/c7n_azure/session.py` (AzureCredential, 150+ lines)
**GCP**: `/home/user/cloud-custodian/tools/c7n_gcp/c7n_gcp/client.py` (client initialization, 100+ lines)

**Issue**: Each cloud reimplements credential caching and session factory
**Solution**: Create abstract SessionFactory base class in c7n core

```python
# Proposed: c7n/credentials/base.py
class BaseSessionFactory:
    """Abstract session factory"""
    
    def __init__(self, region, **options):
        self.region = region
        self.options = options
    
    def get_session(self):
        """Return a session for API calls"""
        raise NotImplementedError()
    
    @property
    def cache_key(self):
        """Unique key for caching credentials"""
        raise NotImplementedError()
```

### 8.3 Action Pattern Duplication

**Duplication**: Delete, Tag, Label actions exist in all clouds

**Current**:
- `c7n/actions/core.py` - AWS base
- `c7n_azure/c7n_azure/actions/delete.py` - Azure delete
- `c7n_gcp/c7n_gcp/actions/core.py` - GCP action base

**Recommendation**: Create shared action base classes in c7n core:

```python
# Proposed: c7n/actions/cloud.py
class DeleteAction(BaseAction):
    """Generic delete action for any resource"""
    
    def process(self, resources):
        # Cloud-specific implementation via abstract method
        for resource in resources:
            try:
                self.delete_resource(resource)
            except self.cloud_error_class as e:
                self.handle_error(e, resource)
    
    @abstractmethod
    def delete_resource(self, resource):
        """Delete a single resource"""
        pass
```

---

## 9. ARCHITECTURE PATTERNS SUMMARY

| Aspect | AWS | Azure | GCP | Best Practice |
|--------|-----|-------|-----|---|
| **Resource Registration** | Distributed per-file | Centralized map | Distributed | Azure (centralized) |
| **Registry Pattern** | Manual in each file | Subscription-based | Per-resource | Azure (subscription) |
| **Metaclass Usage** | Query only | Full TypeInfo | Query only | Azure (comprehensive) |
| **Action Base** | Minimal | Rich (threading) | Minimal | Azure (rich base) |
| **TypeInfo Fields** | 50+ optional | 10-15 focused | 15-20 focused | GCP/Azure (minimal) |
| **Query Pattern** | Multiple classes | Single unified | Source-based | GCP (source-based) |
| **Error Handling** | In actions | In base | In client | Unified base class |
| **Session Management** | Boto3 + cache | Credential class | Discovery API | Abstract factory |
| **Parent-Child Queries** | Special class | Via extra_args | Via parent_spec | Azure (extra_args) |
| **URN/ID Management** | Via generate_arn | Simple | Via TypeInfo | GCP (structured) |

---

## 10. IMPLEMENTATION ROADMAP

### Phase 1: Foundation (2-3 weeks)
1. Create abstract base classes for shared patterns
   - `BaseSessionFactory` in `c7n/credentials/base.py`
   - `CloudError` hierarchy in `c7n/exceptions.py`
   - Shared action base with threading support

2. Migrate AWS resources to use metaclass pattern
   - Update `c7n/query.py` with QueryMeta
   - Gradually migrate resource files

### Phase 2: Query Consolidation (3-4 weeks)
1. Introduce sources pattern for AWS queries
   - Create `c7n/sources/` directory
   - Implement DescribeSource, ConfigSource, etc.
   - Update QueryResourceManager to use sources

2. Consolidate filter/action registration
   - Move to subscription pattern
   - Create central registration hooks

### Phase 3: Metadata Simplification (2-3 weeks)
1. Refactor TypeInfo class hierarchy
   - Split into BaseTypeInfo + mixins
   - Reduce default fields from 50 to 10

2. Document metadata requirements per resource type

### Phase 4: Deduplication (4-6 weeks)
1. Share DeleteAction, TagAction across clouds
2. Share MetricFilter implementations
3. Unify session/credential patterns
4. Create shared error handling

---

## Conclusion

The architecture evolution from AWS to Azure to GCP shows clear improvement in:
1. **Metaclass usage** for automatic wiring
2. **Subscription patterns** for decoupled registration
3. **Minimal metadata** with inheritance
4. **Source abstraction** for pluggable queries
5. **Rich base classes** for common operations

Adopting Azure's subscription pattern and GCP's source abstraction in the AWS core would significantly reduce duplication and improve maintainability. The recommended phased approach allows for gradual migration without breaking existing functionality.

