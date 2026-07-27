# Ingress

The customer may use an existing ingress controller or enable the pinned
ingress-nginx release:

```yaml
ingressNginx:
  enabled: true
```

Application ingress resources are independent:

```yaml
ingress:
  className: nginx
  frontend:
    enabled: true
    host: phoenix.customer.example
    annotations: {}
    tls:
      - secretName: phoenix-customer-tls
        hosts:
          - phoenix.customer.example
```

Gateway ingress is rejected unless
`services.gateway.allowUnauthenticatedIngress=true`. Do not expose it publicly
without an explicit isolation decision.
