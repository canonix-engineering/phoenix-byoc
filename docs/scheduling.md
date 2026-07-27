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
datastores.

Sandbox resource classes are separate from pod placement. Their CPU and memory
requests must fit the customer nodes; otherwise OpenSandbox creation will time
out while pods remain Pending.
