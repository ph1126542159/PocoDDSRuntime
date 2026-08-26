#include "PocoDDS/ServiceClient/HttpInvocationProvider.h"
#include "PocoDDS/ServiceClient/RuntimeCoordinator.h"
#include "PocoDDS/ServiceClient/Testing/ProviderConformance.h"

#include <Poco/Net/HTTPRequestHandler.h>
#include <Poco/Net/HTTPRequestHandlerFactory.h>
#include <Poco/Net/HTTPServer.h>
#include <Poco/Net/HTTPServerParams.h>
#include <Poco/Net/HTTPServerRequest.h>
#include <Poco/Net/HTTPServerResponse.h>
#include <Poco/Net/ServerSocket.h>
#include <Poco/StreamCopier.h>
#include <Poco/TemporaryFile.h>
#include <Poco/Timestamp.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace std::chrono_literals;
using namespace PocoDDS::ServiceClient;
using namespace PocoDDS::ResourceGovernance;
using namespace PocoDDS::ServiceDirectory;

namespace
{
std::atomic<bool> requestContractValid{false};
std::atomic<int> credentialVersion{1};
std::atomic<std::uint64_t> observedHttpRequests{0};

void require(bool condition, const std::string& detail)
{
    if (!condition) throw std::runtime_error(detail);
}

class Handler final : public Poco::Net::HTTPRequestHandler
{
public:
    void handleRequest(Poco::Net::HTTPServerRequest& request,
                       Poco::Net::HTTPServerResponse& response) override
    {
        ++observedHttpRequests;
        std::string body;
        Poco::StreamCopier::copyToString(request.stream(), body);
        const auto operation = request.get("X-PDR-Operation", "");
        bool deadlineValid = false;
        try
        {
            deadlineValid = std::stoll(request.get(
                "X-PDR-Deadline-Unix-Microseconds", "0")) >
                Poco::Timestamp().epochMicroseconds();
        }
        catch (...) {}
        requestContractValid =
            request.getMethod() == Poco::Net::HTTPRequest::HTTP_POST &&
            request.getURI() == "/invoke?fixed=1" &&
            request.get("X-PDR-Service", "") == "orders.v1" &&
            request.get("X-PDR-Invocation-Id", "") ==
                "invocation-http-smoke" &&
            request.get("X-PDR-Attempt", "") == "1" &&
            request.get("X-PDR-Timeout-Milliseconds", "") == "1000" &&
            deadlineValid &&
            request.get("Idempotency-Key", "") == "order-42" &&
            request.get("content-type", "") == "application/octet-stream" &&
            request.get("traceparent", "") == "00-test-trace" &&
            request.get("Authorization", "") ==
                (credentialVersion.load() == 1
                    ? "Bearer provider-secret"
                    : "Bearer provider-secret-v2") &&
            body == "PING";

        if (operation == "retry")
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_SERVICE_UNAVAILABLE);
            response.setContentLength(0);
            response.send();
            return;
        }
        if (operation == "permanent")
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_BAD_REQUEST);
            response.setContentLength(0);
            response.send();
            return;
        }
        if (operation == "redirect")
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_FOUND);
            response.set("Location", "http://127.0.0.1/forbidden");
            response.setContentLength(0);
            response.send();
            return;
        }
        if (operation == "large")
        {
            response.setStatus(Poco::Net::HTTPResponse::HTTP_OK);
            response.setContentLength(32);
            response.send() << std::string(32, 'X');
            return;
        }
        response.setStatus(Poco::Net::HTTPResponse::HTTP_CREATED);
        response.setContentLength(2);
        response.send() << "OK";
    }
};

class Factory final : public Poco::Net::HTTPRequestHandlerFactory
{
public:
    Poco::Net::HTTPRequestHandler* createRequestHandler(
        const Poco::Net::HTTPServerRequest&) override
    {
        return new Handler;
    }
};

class DirectoryService final : public ServiceDirectoryRuntimeService
{
public:
    ObservationResult observe(Advertisement value) override
    {
        return _directory.observe(std::move(value));
    }
    bool withdraw(const std::string& serviceName,
                  const std::string& instanceId,
                  const std::string& runtimeId,
                  std::uint64_t incarnation,
                  std::uint64_t revision) override
    {
        return _directory.withdraw(serviceName, instanceId, runtimeId,
                                   incarnation, revision);
    }
    PocoDDS::ServiceDirectory::Snapshot snapshot() const override
    {
        return _directory.snapshot();
    }
    RouteResult route(const RouteRequest& request) override
    {
        return _router.select(_directory.snapshot(), request);
    }

private:
    Directory _directory;
    Router _router;
};

class GovernorService final : public ResourceGovernorService
{
public:
    GovernorService()
        : _governor(PocoDDS::ResourceGovernance::Policy{
              "*", 1, 4, 1000ms, 2000ms, 3, 100ms})
    {
    }

    Admission submit(const std::string& owner, WorkItem item) override
    {
        return _governor.submit(owner, std::move(item));
    }
    PocoDDS::ResourceGovernance::Snapshot snapshot(
        const std::string& owner) const override
    {
        return _governor.snapshot(owner);
    }
    std::vector<PocoDDS::ResourceGovernance::Snapshot> snapshots()
        const override
    {
        return _governor.snapshots();
    }

private:
    ResourceGovernor _governor;
};

ProviderInvocationRequest invocation(std::uint16_t port,
                                     const std::string& operation)
{
    ProviderInvocationRequest value;
    value.invocationId = "invocation-http-smoke";
    value.deadlineUnixMicroseconds =
        Poco::Timestamp().epochMicroseconds() + 5000000;
    value.attempt.instance.advertisement.serviceName = "orders.v1";
    value.attempt.instance.advertisement.instanceId = "orders-a";
    value.attempt.instance.advertisement.runtimeId = "runtime-a";
    value.attempt.instance.advertisement.runtimeIncarnation = 1;
    value.attempt.instance.advertisement.protocol = "http";
    value.attempt.instance.advertisement.endpoint =
        "http://127.0.0.1:" + std::to_string(port) + "/invoke?fixed=1";
    value.attempt.remaining = 1000ms;
    value.attempt.attempt = 1;
    value.attempt.operation = operation;
    value.attempt.idempotencyKey = "order-42";
    auto input = std::make_shared<InvocationInput>();
    input->payload = {'P', 'I', 'N', 'G'};
    input->metadata["content-type"] = "application/octet-stream";
    input->metadata["traceparent"] = "00-test-trace";
    value.input = std::move(input);
    value.cancellationRequested = [] { return false; };
    return value;
}
} // namespace

int main()
{
    try
    {
        bool invalidOptionsRejected = false;
        try
        {
            HttpInvocationOptions invalid;
            invalid.providerId = "invalid";
            invalid.protocol = "http";
            Poco::AutoPtr<HttpInvocationProvider> unused =
                new HttpInvocationProvider(std::move(invalid));
        }
        catch (const std::invalid_argument&)
        {
            invalidOptionsRejected = true;
        }
        require(invalidOptionsRejected,
                "Provider accepted an empty egress policy");

        bool invalidHostRejected = false;
        try
        {
            HttpInvocationOptions invalid;
            invalid.providerId = "invalid-host";
            invalid.protocol = "http";
            invalid.allowedHosts = {"http://not-a-host"};
            invalid.allowedPorts = {80};
            Poco::AutoPtr<HttpInvocationProvider> unused =
                new HttpInvocationProvider(std::move(invalid));
        }
        catch (const std::invalid_argument&)
        {
            invalidHostRejected = true;
        }
        require(invalidHostRejected,
                "Provider accepted a malformed host allowlist entry");

        Poco::Net::ServerSocket socket(Poco::Net::SocketAddress("127.0.0.1", 0));
        const auto port = socket.address().port();
        Poco::Net::HTTPServer server(
            new Factory, socket, new Poco::Net::HTTPServerParams);
        server.start();

        Poco::TemporaryFile credentialFile;
        const auto writeCredential = [&](const std::string& value) {
            std::ofstream stream(
                credentialFile.path(), std::ios::binary | std::ios::trunc);
            stream << value;
            stream.close();
            require(stream.good(), "failed to write credential test file");
        };
        writeCredential("Bearer provider-secret\n");

        HttpInvocationOptions options;
        options.providerId = "builtin-http";
        options.protocol = "http";
        options.allowedHosts = {"127.0.0.1"};
        options.allowedPorts = {port};
        options.allowLoopback = true;
        options.maximumRequestBytes = 16;
        options.maximumResponseBytes = 16;
        options.maximumTimeout = 1000ms;
        options.authorizationRules.push_back({
            "orders.v1", "*", "127.0.0.1", port,
            "", credentialFile.path()});
        options.requireAuthorizationMatch = true;
        options.requireRestrictedCredentialFiles = false;
        options.credentialReloadInterval = 0ms;
        Poco::AutoPtr<HttpInvocationProvider> provider =
            new HttpInvocationProvider(options);

        const auto success = provider->invoke(invocation(port, "read"));
        if (success.disposition != AttemptDisposition::succeeded ||
            success.payload != std::vector<std::uint8_t>({'O', 'K'}) ||
            !requestContractValid.load())
            std::cerr << "success disposition="
                      << static_cast<int>(success.disposition)
                      << " code=" << success.code
                      << " detail=" << success.detail
                      << " payload=" << success.payload.size()
                      << " requestContract=" << requestContractValid.load()
                      << '\n';
        require(success.disposition == AttemptDisposition::succeeded &&
                    success.payload == std::vector<std::uint8_t>({'O', 'K'}) &&
                    requestContractValid.load(),
                "HTTP success response or outbound request contract is incorrect");

        PocoDDS::ServiceClient::Testing::ProviderConformanceExpectations
            conformance;
        conformance.providerId = "builtin-http";
        conformance.protocol = "http";
        conformance.validRequest = invocation(port, "read");
        conformance.validResult = [](const AttemptResult& result) {
            return result.payload ==
                std::vector<std::uint8_t>({'O', 'K'});
        };
        conformance.observedInvocations = [] {
            return observedHttpRequests.load();
        };
        conformance.maximumCallDuration = 2000ms;
        const auto conformanceResult =
            PocoDDS::ServiceClient::Testing::runProviderConformance(
                *provider, conformance);
        require(conformanceResult.passed,
                "HTTP Provider failed shared conformance TCK: " +
                    conformanceResult.failedCheck + " " +
                    conformanceResult.detail);

        auto initialCredentials = provider->credentialSnapshot();
        require(initialCredentials.healthy &&
                    initialCredentials.fileBackedRules == 1 &&
                    initialCredentials.generation == 1 &&
                    initialCredentials.reloads == 0,
                "initial file-backed credential snapshot is incorrect");
        credentialVersion = 2;
        writeCredential("Bearer provider-secret-v2\n");
        requestContractValid = false;
        require(provider->invoke(invocation(port, "read")).disposition ==
                    AttemptDisposition::succeeded &&
                    requestContractValid.load(),
                "rotated credential was not used without recreating Provider");
        auto rotatedCredentials = provider->credentialSnapshot();
        require(rotatedCredentials.healthy &&
                    rotatedCredentials.generation == 2 &&
                    rotatedCredentials.reloads == 1 &&
                    rotatedCredentials.reloadFailures == 0,
                "successful credential rotation was not recorded");

        writeCredential("");
        require(provider->invoke(invocation(port, "read")).code ==
                    "http-credential-reload-failed",
                "empty credential rotation did not fail closed before network I/O");
        auto failedCredentials = provider->credentialSnapshot();
        require(!failedCredentials.healthy &&
                    failedCredentials.generation == 2 &&
                    failedCredentials.reloads == 1 &&
                    failedCredentials.reloadFailures >= 1 &&
                    failedCredentials.lastError.find(
                        "provider-secret") == std::string::npos,
                "failed credential reload replaced or leaked the valid snapshot");

        writeCredential("Bearer provider-secret-v2\n");
        std::vector<std::thread> credentialReaders;
        std::atomic<int> credentialReadFailures{0};
        for (int index = 0; index < 8; ++index)
        {
            credentialReaders.emplace_back([&] {
                const auto result = provider->invoke(invocation(port, "read"));
                if (result.disposition != AttemptDisposition::succeeded)
                    ++credentialReadFailures;
            });
        }
        for (auto& reader : credentialReaders) reader.join();
        require(credentialReadFailures.load() == 0 &&
                    provider->credentialSnapshot().healthy,
                "concurrent calls did not recover on a valid credential file");

        const auto retry = provider->invoke(invocation(port, "retry"));
        require(retry.disposition == AttemptDisposition::retryableFailure &&
                    retry.code == "http-retryable-status",
                "HTTP 503 was not classified as retryable");
        const auto permanent = provider->invoke(invocation(port, "permanent"));
        require(permanent.disposition == AttemptDisposition::permanentFailure &&
                    permanent.endpointHealthy &&
                    permanent.code == "http-permanent-status",
                "HTTP 400 was not classified as a healthy permanent failure");
        const auto redirect = provider->invoke(invocation(port, "redirect"));
        require(redirect.code == "http-redirect-rejected",
                "HTTP redirect was followed or misclassified");
        const auto large = provider->invoke(invocation(port, "large"));
        require(large.code == "http-response-too-large",
                "oversized HTTP response was accepted");

        auto deniedMetadata = invocation(port, "read");
        auto metadataInput = std::make_shared<InvocationInput>(*deniedMetadata.input);
        metadataInput->metadata["authorization"] = "attacker-controlled";
        deniedMetadata.input = metadataInput;
        require(provider->invoke(deniedMetadata).code == "http-metadata-denied",
                "sensitive caller metadata was forwarded");

        auto oversized = invocation(port, "read");
        auto oversizedInput = std::make_shared<InvocationInput>(*oversized.input);
        oversizedInput->payload.assign(17, 0x41);
        oversized.input = oversizedInput;
        require(provider->invoke(oversized).code == "http-request-too-large",
                "oversized HTTP request was accepted");

        auto cancelled = invocation(port, "read");
        cancelled.cancellationRequested = [] { return true; };
        require(provider->invoke(cancelled).code == "cancelled",
                "pre-cancelled HTTP request reached the network");

        auto deniedHost = invocation(port, "read");
        deniedHost.attempt.instance.advertisement.endpoint =
            "http://localhost:" + std::to_string(port) + "/invoke";
        require(provider->invoke(deniedHost).code == "http-host-denied",
                "non-allowlisted host was accepted");

        auto unboundCredential = invocation(port, "read");
        unboundCredential.attempt.instance.advertisement.serviceName =
            "inventory.v1";
        require(provider->invoke(unboundCredential).code ==
                    "http-credential-binding-missing",
                "target-bound credential was reused for another service");

        HttpInvocationOptions locked = options;
        locked.providerId = "locked-http";
        locked.allowLoopback = false;
        Poco::AutoPtr<HttpInvocationProvider> lockedProvider =
            new HttpInvocationProvider(std::move(locked));
        require(lockedProvider->invoke(invocation(port, "read")).code ==
                    "http-address-denied",
                "loopback endpoint bypassed the address policy");

        HttpInvocationOptions mappedOptions = options;
        mappedOptions.providerId = "mapped-http";
        mappedOptions.allowedHosts = {"::ffff:127.0.0.1"};
        mappedOptions.allowLoopback = false;
        mappedOptions.authorizationRules = {{
            "orders.v1", "*", "::ffff:127.0.0.1", port,
            "Bearer provider-secret"}};
        Poco::AutoPtr<HttpInvocationProvider> mappedProvider =
            new HttpInvocationProvider(std::move(mappedOptions));
        auto mappedLoopback = invocation(port, "read");
        mappedLoopback.attempt.instance.advertisement.endpoint =
            "http://[::ffff:127.0.0.1]:" + std::to_string(port) + "/invoke";
        require(mappedProvider->invoke(mappedLoopback).code ==
                    "http-address-denied",
                "IPv4-mapped IPv6 loopback bypassed the address policy");

        auto wrongScheme = invocation(port, "read");
        wrongScheme.attempt.instance.advertisement.endpoint =
            "https://127.0.0.1:" + std::to_string(port) + "/invoke";
        require(provider->invoke(wrongScheme).code == "http-endpoint-invalid",
                "endpoint scheme did not match the registered protocol");

        Poco::AutoPtr<DirectoryService> directory = new DirectoryService;
        Advertisement advertisement;
        advertisement.serviceName = "orders.v1";
        advertisement.instanceId = "orders-http-a";
        advertisement.runtimeId = "runtime-http-a";
        advertisement.runtimeIncarnation = 1;
        advertisement.revision = 1;
        advertisement.endpoint =
            "http://127.0.0.1:" + std::to_string(port) + "/invoke?fixed=1";
        advertisement.protocol = "http";
        require(static_cast<bool>(directory->observe(std::move(advertisement))),
                "HTTP service advertisement was rejected");
        Poco::AutoPtr<GovernorService> governor = new GovernorService;
        RuntimeOptions runtimeOptions;
        runtimeOptions.resourceOwner = "test.http-invocation";
        runtimeOptions.client.maximumAttempts = 1;
        runtimeOptions.client.timeout = 1000ms;
        runtimeOptions.maximumPayloadBytes = 16;
        runtimeOptions.maximumMetadataEntries = 4;
        runtimeOptions.maximumMetadataBytes = 128;
        RuntimeCoordinator coordinator(runtimeOptions, directory, governor);
        require(static_cast<bool>(coordinator.attach(provider)),
                "HTTP Provider did not attach to RuntimeCoordinator");

        RuntimeInvocationRequest governed;
        governed.workId = "http-governed-1";
        governed.invocation.route.serviceName = "orders.v1";
        governed.invocation.operation = "governed";
        governed.invocation.idempotencyKey = "order-42";
        governed.input.payload = {'P', 'I', 'N', 'G'};
        governed.input.metadata["content-type"] = "application/octet-stream";
        governed.input.metadata["traceparent"] = "00-test-trace";
        const auto submission = coordinator.submit(std::move(governed));
        require(static_cast<bool>(submission) &&
                    submission.completion.wait_for(3s) ==
                        std::future_status::ready,
                "governed HTTP invocation did not complete");
        const auto completion = submission.completion.get();
        const auto runtimeState = coordinator.snapshot();
        require(completion.governance.status == CompletionStatus::succeeded &&
                    completion.invocation && *completion.invocation &&
                    completion.invocation->payload ==
                        std::vector<std::uint8_t>({'O', 'K'}) &&
                    runtimeState.providerRegistry.providers.size() == 1 &&
                    runtimeState.providerRegistry.providers[0].dispatched == 1 &&
                    runtimeState.resourceLane.succeeded == 1,
                "HTTP invocation did not traverse routing, governance and Provider layers");
        coordinator.shutdown();

        server.stop();
        std::cout << "HTTP_INVOCATION_PROVIDER_PASS port=" << port
                  << " governed=" << runtimeState.resourceLane.succeeded
                  << " conformance="
                  << conformanceResult.report.passedChecks.size() << '\n';
        return 0;
    }
    catch (const std::exception& exception)
    {
        std::cerr << "HTTP_INVOCATION_PROVIDER_ERROR: "
                  << exception.what() << '\n';
        return 1;
    }
}
