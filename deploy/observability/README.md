# 本地生产监控栈

该目录提供 mTLS OpenTelemetry Collector、Prometheus、Grafana Dashboard 和告警规则。Runtime 直接使用 OpenTelemetry C++ 官方 OTLP/HTTP Exporter，不需要项目内协议适配器。

```powershell
.\generate-certificates.ps1
$env:GRAFANA_ADMIN_PASSWORD = "replace-with-a-local-secret"
docker compose up -d
```

Runtime 配置：

```properties
observability.metrics.otlpHttpEndpoint = https://localhost:4318
observability.metrics.otlpCaCertificatePath = ../../deploy/observability/certificates/ca.crt
observability.metrics.otlpClientCertificatePath = ../../deploy/observability/certificates/client.crt
observability.metrics.otlpClientKeyPath = ../../deploy/observability/certificates/client.key
observability.metrics.otlpInsecureSkipVerify = false
```

入口：Prometheus `http://127.0.0.1:9090`，Grafana `http://127.0.0.1:3000`。Collector 的 4318 端口要求客户端证书，没有证书、证书不受信任或主机名校验失败时必须拒绝连接。

不要提交 `certificates/*.key`、生成的证书或 Grafana 密码。生产环境应改用组织 CA 和 Secret 管理系统。
