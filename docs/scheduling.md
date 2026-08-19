# Scheduling

Phoenix does not create or modify node labels. The customer supplies placement:

```yaml
scheduling:
  nodeSelector:
    workload.example.com/class: phoenix
  tolerations:
    - key: workload.example.com/class
      operator: Equal
      value: phoenix
      effect: NoSchedule
  affinity: {}
```

These values are passed to application workloads and optional bundled
datastores. The supplied example matches the Phoenix `test` environment; a
customer must replace or remove the `canonix.ai/node-role` placement before
installing into a cluster with different node labels or taints.

Dynamic sandbox Pods are placed independently through every entry under
`scheduling.sandboxResourceClasses`. Each class accepts `nodeSelector`,
`tolerations` and `affinity` alongside its CPU and memory settings:

```yaml
scheduling:
  sandboxResourceClasses:
    high-cpu:
      nodeSelector:
        workload.example.com/class: phoenix-sandbox
      tolerations:
        - key: workload.example.com/class
          operator: Equal
          value: phoenix-sandbox
          effect: NoSchedule
      affinity: {}
      resources:
        requests: {cpu: "2000m", memory: "8Gi"}
        limits: {cpu: "2000m", memory: "8Gi"}
```

CPU and memory requests must fit the selected customer nodes; otherwise
OpenSandbox creation times out while Pods remain Pending.
