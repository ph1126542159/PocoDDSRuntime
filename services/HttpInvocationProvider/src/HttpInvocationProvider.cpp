#include "PocoDDS/ServiceClient/HttpInvocationProvider.h"
#include "PocoDDS/Security/SecretFile.h"

#include <Poco/Exception.h>
#include <Poco/Net/Context.h>
#include <Poco/Net/DNS.h>
#include <Poco/Net/HTTPClientSession.h>
#include <Poco/Net/HTTPRequest.h>
#include <Poco/Net/HTTPResponse.h>
#include <Poco/Net/HTTPSClientSession.h>
#include <Poco/Net/IPAddress.h>
#include <Poco/Net/SSLException.h>
#include <Poco/Net/SecureStreamSocket.h>
#include <Poco/Net/SocketAddress.h>
#include <Poco/Timespan.h>
#include <Poco/Timestamp.h>
#include <Poco/URI.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace PocoDDS::ServiceClient
{
namespace
{
std::string lower(std::string value)
{
    std::transform(value.begin(), value.end(), value.begin(),
        [](unsigned char character) {
            return static_cast<char>(std::tolower(character));
        });
    while (value.size() > 1 && value.back() == '.') value.pop_back();
    return value;
}

bool visibleAscii(const std::string& value, std::size_t maximum,
                  bool allowEmpty = false)
{
    if ((!allowEmpty && value.empty()) || value.size() > maximum) return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return character >= 0x21 && character <= 0x7e;
    });
}

bool headerValue(const std::string& value, std::size_t maximum)
{
    return value.size() <= maximum &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return character >= 0x20 && character != 0x7f;
        });
}

bool validDnsName(const std::string& name)
{
    if (!visibleAscii(name, 253)) return false;
    std::size_t begin = 0;
    while (begin < name.size())
    {
        const auto end = name.find('.', begin);
        const auto size = (end == std::string::npos ? name.size() : end) - begin;
        if (size == 0 || size > 63 || name[begin] == '-' ||
            name[begin + size - 1] == '-')
            return false;
        for (std::size_t offset = 0; offset < size; ++offset)
        {
            const auto character = static_cast<unsigned char>(name[begin + offset]);
            if (!std::isalnum(character) && character != '-') return false;
        }
        if (end == std::string::npos) return true;
        begin = end + 1;
    }
    return false;
}

bool validHostPattern(const std::string& pattern)
{
    if (!visibleAscii(pattern, 253)) return false;
    Poco::Net::IPAddress literal;
    if (Poco::Net::IPAddress::tryParse(pattern, literal)) return true;
    if (pattern.rfind("*.", 0) == 0)
        return pattern.find('*', 1) == std::string::npos &&
               validDnsName(pattern.substr(2));
    return pattern.find('*') == std::string::npos && validDnsName(pattern);
}

bool hostMatches(const std::string& host, const std::string& pattern)
{
    if (pattern.rfind("*.", 0) != 0) return host == pattern;
    const auto suffix = pattern.substr(1);
    return host.size() > suffix.size() &&
           host.compare(host.size() - suffix.size(), suffix.size(), suffix) == 0;
}

bool validTargetPattern(const std::string& value)
{
    if (!visibleAscii(value, 128)) return false;
    const auto star = value.find('*');
    if (star != std::string::npos &&
        (star != value.size() - 1 || value.find('*', star + 1) != std::string::npos))
        return false;
    return std::all_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isalnum(character) || character == '.' || character == '-' ||
               character == '_' || character == ':' || character == '/' ||
               character == '*';
    });
}

bool targetMatches(const std::string& value, const std::string& pattern)
{
    if (!pattern.empty() && pattern.back() == '*')
        return value.compare(0, pattern.size() - 1, pattern, 0,
                             pattern.size() - 1) == 0;
    return value == pattern;
}

std::optional<Poco::Net::IPAddress::RawIPv4> ipv4Bytes(
    const Poco::Net::IPAddress& address)
{
    if (address.family() == Poco::Net::IPAddress::IPv4)
        return address.toV4Bytes();
    if (address.family() == Poco::Net::IPAddress::IPv6 &&
        address.isIPv4Mapped())
    {
        const auto mapped = address.toV6Bytes();
        return Poco::Net::IPAddress::RawIPv4{
            mapped[12], mapped[13], mapped[14], mapped[15]};
    }
    return std::nullopt;
}

bool loopbackAddress(const Poco::Net::IPAddress& address)
{
    const auto bytes = ipv4Bytes(address);
    return address.isLoopback() || (bytes && (*bytes)[0] == 127);
}

bool linkLocalAddress(const Poco::Net::IPAddress& address)
{
    const auto bytes = ipv4Bytes(address);
    return address.isLinkLocal() ||
           (bytes && (*bytes)[0] == 169 && (*bytes)[1] == 254);
}

bool privateAddress(const Poco::Net::IPAddress& address)
{
    const auto bytes = ipv4Bytes(address);
    if (!bytes) return address.isSiteLocal();
    return (*bytes)[0] == 10 ||
           ((*bytes)[0] == 172 && (*bytes)[1] >= 16 && (*bytes)[1] <= 31) ||
           ((*bytes)[0] == 192 && (*bytes)[1] == 168) ||
           ((*bytes)[0] == 100 && (*bytes)[1] >= 64 && (*bytes)[1] <= 127) ||
           ((*bytes)[0] == 198 && ((*bytes)[1] == 18 || (*bytes)[1] == 19));
}

bool reservedAddress(const Poco::Net::IPAddress& address)
{
    if (const auto bytes = ipv4Bytes(address))
    {
        return (*bytes)[0] == 0 || (*bytes)[0] >= 224 ||
               ((*bytes)[0] == 192 && (*bytes)[1] == 0 &&
                    ((*bytes)[2] == 0 || (*bytes)[2] == 2)) ||
               ((*bytes)[0] == 198 && (*bytes)[1] == 51 &&
                    (*bytes)[2] == 100) ||
               ((*bytes)[0] == 203 && (*bytes)[1] == 0 &&
                    (*bytes)[2] == 113);
    }
    if (address.family() == Poco::Net::IPAddress::IPv6)
    {
        const auto bytes = address.toV6Bytes();
        return (bytes[0] == 0x01 &&
                std::all_of(bytes.begin() + 1, bytes.begin() + 8,
                            [](unsigned char value) { return value == 0; })) ||
               (bytes[0] == 0x00 && bytes[1] == 0x64 &&
                bytes[2] == 0xff && bytes[3] == 0x9b) ||
               (bytes[0] == 0x20 && bytes[1] == 0x02) ||
               (bytes[0] == 0x20 && bytes[1] == 0x01 &&
                bytes[2] == 0x00 && bytes[3] == 0x00) ||
               (bytes[0] == 0x20 && bytes[1] == 0x01 &&
                bytes[2] == 0x0d && bytes[3] == 0xb8);
    }
    return true;
}

std::optional<std::string> addressPolicyIssue(
    const Poco::Net::IPAddress& address,
    const HttpInvocationOptions& options)
{
    if (!address.isUnicast() || address.isWildcard() || address.isBroadcast() ||
        address.isMulticast() || reservedAddress(address))
        return "resolved address is non-unicast or reserved";
    if (loopbackAddress(address) && !options.allowLoopback)
        return "resolved address is loopback";
    if (linkLocalAddress(address) && !options.allowLinkLocal)
        return "resolved address is link-local";
    if (privateAddress(address) && !options.allowPrivateNetworks)
        return "resolved address is private";
    return std::nullopt;
}

bool retryableStatus(int status)
{
    return status == 408 || status == 425 || status == 429 || status >= 500;
}

std::string statusDetail(int status)
{
    return "HTTP endpoint returned status " + std::to_string(status);
}
} // namespace

class HttpInvocationProvider::Impl
{
public:
    struct CredentialState
    {
        mutable std::mutex mutex;
        std::string value;
        std::string file;
        std::chrono::steady_clock::time_point nextCheck{};
        std::uint64_t generation{1};
        std::uint64_t reloads{0};
        std::uint64_t reloadFailures{0};
        bool healthy{true};
        bool permissionsVerified{false};
        bool restricted{false};
        std::string lastError;
    };

    explicit Impl(HttpInvocationOptions value): options(std::move(value))
    {
        options.providerId = lower(options.providerId);
        options.protocol = lower(options.protocol);
        if (!visibleAscii(options.providerId, 128) ||
            (options.protocol != "http" && options.protocol != "https"))
            throw std::invalid_argument(
                "HTTP invocation Provider identity or protocol is invalid");
        if (options.allowedHosts.empty() || options.allowedHosts.size() > 256 ||
            options.allowedPorts.empty() || options.allowedPorts.size() > 256)
            throw std::invalid_argument(
                "HTTP invocation Provider requires 1..256 allowed hosts and ports");
        std::set<std::string> hosts;
        for (auto& pattern : options.allowedHosts)
        {
            pattern = lower(pattern);
            if (!validHostPattern(pattern) || !hosts.insert(pattern).second)
                throw std::invalid_argument(
                    "HTTP invocation Provider host policy is invalid or duplicated");
        }
        std::set<std::uint16_t> ports;
        for (const auto port : options.allowedPorts)
        {
            if (port == 0 || !ports.insert(port).second)
                throw std::invalid_argument(
                    "HTTP invocation Provider port policy is invalid or duplicated");
        }
        if (options.maximumRequestBytes == 0 ||
            options.maximumRequestBytes > 16 * 1024 * 1024 ||
            options.maximumResponseBytes == 0 ||
            options.maximumResponseBytes > 16 * 1024 * 1024 ||
            options.maximumTimeout.count() <= 0 ||
            options.maximumTimeout > std::chrono::hours(1) ||
            options.credentialReloadInterval.count() < 0 ||
            options.credentialReloadInterval > std::chrono::hours(1))
            throw std::invalid_argument(
                "HTTP invocation Provider resource limits are invalid");
        if (!headerValue(options.authorization, 8192))
            throw std::invalid_argument(
                "HTTP invocation Provider authorization value is invalid");
        if (!options.authorization.empty() && !options.authorizationRules.empty())
            throw std::invalid_argument(
                "HTTP invocation Provider cannot mix global and target-bound authorization");
        if (options.authorizationRules.size() > 256)
            throw std::invalid_argument(
                "HTTP invocation Provider accepts at most 256 authorization rules");
        std::set<std::string> authorizationKeys;
        credentialStates.reserve(options.authorizationRules.size());
        for (auto& rule : options.authorizationRules)
        {
            rule.host = lower(rule.host);
            const bool inlineAuthorization = !rule.authorization.empty();
            const bool fileAuthorization = !rule.authorizationFile.empty();
            if (!validTargetPattern(rule.service) ||
                !validTargetPattern(rule.operation) ||
                !validHostPattern(rule.host) ||
                !headerValue(rule.authorization, 8192) ||
                inlineAuthorization == fileAuthorization)
                throw std::invalid_argument(
                    "HTTP invocation Provider authorization rule is invalid");
            const auto key = rule.service + "\n" + rule.operation + "\n" +
                rule.host + "\n" + std::to_string(rule.port);
            if (!authorizationKeys.insert(key).second)
                throw std::invalid_argument(
                    "HTTP invocation Provider authorization rule is duplicated");
            if (!fileAuthorization)
            {
                credentialStates.push_back(nullptr);
                continue;
            }

            auto material = Security::loadSecretFile(
                rule.authorizationFile, 8192,
                "HTTP authorization credential");
            if (!headerValue(material.value, 8192))
                throw std::invalid_argument(
                    "HTTP authorization credential file contains an invalid header value");
            if (options.requireRestrictedCredentialFiles &&
                (!material.permissionsVerified || !material.restricted))
                throw std::invalid_argument(
                    "HTTP authorization credential file permissions are not restricted");
            auto state = std::make_unique<CredentialState>();
            state->value = std::move(material.value);
            state->file = std::move(material.absolutePath);
            state->permissionsVerified = material.permissionsVerified;
            state->restricted = material.restricted;
            state->nextCheck = std::chrono::steady_clock::now() +
                options.credentialReloadInterval;
            rule.authorizationFile = state->file;
            credentialStates.push_back(std::move(state));
        }
        if (options.requireAuthorizationMatch &&
            options.authorization.empty() && options.authorizationRules.empty())
            throw std::invalid_argument(
                "HTTP invocation Provider requires authorization but has no credential binding");

        if (options.protocol == "https")
        {
            Poco::Net::Context::Params parameters;
            parameters.caLocation = options.caCertificate;
            parameters.verificationMode = Poco::Net::Context::VERIFY_STRICT;
            parameters.loadDefaultCAs = parameters.caLocation.empty();
            tlsContext = new Poco::Net::Context(
                Poco::Net::Context::TLS_CLIENT_USE, parameters);
            tlsContext->enableExtendedCertificateVerification(true);
        }
        else if (!options.caCertificate.empty())
            throw std::invalid_argument(
                "HTTP invocation Provider CA certificate requires HTTPS");
    }

    bool allowedHost(const std::string& host) const
    {
        return std::any_of(options.allowedHosts.begin(), options.allowedHosts.end(),
            [&](const std::string& pattern) { return hostMatches(host, pattern); });
    }

    bool allowedPort(std::uint16_t port) const
    {
        return std::find(options.allowedPorts.begin(), options.allowedPorts.end(),
                         port) != options.allowedPorts.end();
    }

    std::optional<std::string> authorizationFor(
        const AttemptContext& attempt, const std::string& host,
        std::uint16_t port, bool& ambiguous, bool& unavailable) const
    {
        ambiguous = false;
        unavailable = false;
        if (!options.authorization.empty()) return options.authorization;
        std::size_t selected = options.authorizationRules.size();
        std::size_t selectedScore = 0;
        for (std::size_t index = 0;
             index < options.authorizationRules.size(); ++index)
        {
            const auto& rule = options.authorizationRules[index];
            if (!targetMatches(attempt.instance.advertisement.serviceName,
                               rule.service) ||
                !targetMatches(attempt.operation, rule.operation) ||
                !hostMatches(host, rule.host) ||
                (rule.port != 0 && rule.port != port))
                continue;
            const auto score =
                (rule.service.back() == '*' ? 0u : 8u) +
                (rule.operation.back() == '*' ? 0u : 4u) +
                (rule.host.rfind("*.", 0) == 0 ? 0u : 2u) +
                (rule.port == 0 ? 0u : 1u);
            if (selected == options.authorizationRules.size() ||
                score > selectedScore)
            {
                selected = index;
                selectedScore = score;
                ambiguous = false;
            }
            else if (score == selectedScore)
                ambiguous = true;
        }
        if (selected == options.authorizationRules.size() || ambiguous)
            return std::nullopt;
        if (!credentialStates[selected])
            return options.authorizationRules[selected].authorization;
        return reloadCredential(*credentialStates[selected], unavailable);
    }

    std::optional<std::string> reloadCredential(
        CredentialState& state, bool& unavailable) const
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        const auto now = std::chrono::steady_clock::now();
        if (now < state.nextCheck)
        {
            unavailable = !state.healthy;
            return state.healthy
                ? std::optional<std::string>(state.value)
                : std::nullopt;
        }
        state.nextCheck = now + options.credentialReloadInterval;
        try
        {
            auto material = Security::loadSecretFile(
                state.file, 8192, "HTTP authorization credential");
            if (!headerValue(material.value, 8192))
                throw std::invalid_argument(
                    "credential is not a valid HTTP header value");
            if (options.requireRestrictedCredentialFiles &&
                (!material.permissionsVerified || !material.restricted))
                throw std::invalid_argument(
                    "credential file permissions are not restricted");
            if (material.value != state.value)
            {
                state.value = std::move(material.value);
                ++state.generation;
                ++state.reloads;
            }
            state.permissionsVerified = material.permissionsVerified;
            state.restricted = material.restricted;
            state.healthy = true;
            state.lastError.clear();
            return state.value;
        }
        catch (...)
        {
            ++state.reloadFailures;
            state.healthy = false;
            state.lastError =
                "credential file reload validation failed";
            unavailable = true;
            return std::nullopt;
        }
    }

    HttpCredentialSnapshot credentialSnapshot() const
    {
        HttpCredentialSnapshot result;
        for (const auto& state : credentialStates)
        {
            if (!state) continue;
            ++result.fileBackedRules;
            std::lock_guard<std::mutex> lock(state->mutex);
            result.generation += state->generation;
            result.reloads += state->reloads;
            result.reloadFailures += state->reloadFailures;
            result.healthy = result.healthy && state->healthy;
            result.permissionChecksComplete =
                result.permissionChecksComplete &&
                state->permissionsVerified;
            if (state->permissionsVerified && !state->restricted)
                ++result.insecureFiles;
            if (result.lastError.empty() && !state->lastError.empty())
                result.lastError = state->lastError;
        }
        return result;
    }

    std::unique_ptr<Poco::Net::HTTPClientSession> session(
        const Poco::URI& uri, const Poco::Net::IPAddress& address,
        std::chrono::milliseconds timeout) const
    {
        std::unique_ptr<Poco::Net::HTTPClientSession> result;
        if (options.protocol == "https")
        {
            Poco::Net::SecureStreamSocket socket(uri.getHost(), tlsContext);
            result = std::make_unique<Poco::Net::HTTPSClientSession>(
                socket, address.toString(), uri.getPort());
        }
        else
            result = std::make_unique<Poco::Net::HTTPClientSession>(
                Poco::Net::SocketAddress(address, uri.getPort()));
        result->setProxyConfig({});
        result->setTimeout(Poco::Timespan(
            static_cast<Poco::Int64>(timeout.count()) * 1000));
        return result;
    }

    HttpInvocationOptions options;
    std::vector<std::unique_ptr<CredentialState>> credentialStates;
    Poco::Net::Context::Ptr tlsContext;
};

HttpInvocationProvider::HttpInvocationProvider(HttpInvocationOptions options)
    : _impl(std::make_unique<Impl>(std::move(options)))
{
}

HttpInvocationProvider::~HttpInvocationProvider() = default;

std::string HttpInvocationProvider::providerId() const
{
    return _impl->options.providerId;
}

std::string HttpInvocationProvider::protocol() const
{
    return _impl->options.protocol;
}

HttpCredentialSnapshot HttpInvocationProvider::credentialSnapshot() const
{
    return _impl->credentialSnapshot();
}

AttemptResult HttpInvocationProvider::invoke(
    const ProviderInvocationRequest& request)
{
    if (!request.input)
        return AttemptResult::permanent(
            "http-input-invalid", "HTTP invocation input is required");
    if (!visibleAscii(request.invocationId, 128))
        return AttemptResult::permanent(
            "http-invocation-id-invalid",
            "HTTP invocation ID must be visible ASCII within 128 characters");
    if (request.cancellationRequested && request.cancellationRequested())
        return AttemptResult::permanent(
            "cancelled", "HTTP invocation was cancelled before endpoint validation",
            true);
    if (request.attempt.remaining <= std::chrono::milliseconds{0} ||
        (request.deadlineUnixMicroseconds > 0 &&
         request.deadlineUnixMicroseconds <=
             Poco::Timestamp().epochMicroseconds()))
        return AttemptResult::permanent(
            "deadline-exceeded",
            "HTTP invocation deadline expired before endpoint validation",
            true);
    if (!visibleAscii(request.attempt.operation, 128))
        return AttemptResult::permanent(
            "http-operation-invalid",
            "HTTP invocation operation must be visible ASCII within 128 characters");
    if (request.input->payload.size() > _impl->options.maximumRequestBytes)
        return AttemptResult::permanent(
            "http-request-too-large",
            "HTTP invocation payload exceeds Provider capacity");

    Poco::URI uri;
    try
    {
        const auto& endpoint = request.attempt.instance.advertisement.endpoint;
        if (endpoint.size() > 2048) throw Poco::SyntaxException("endpoint is too long");
        uri = Poco::URI(endpoint);
    }
    catch (const Poco::Exception& exception)
    {
        return AttemptResult::permanent(
            "http-endpoint-invalid", exception.displayText());
    }
    const auto host = lower(uri.getHost());
    if (lower(uri.getScheme()) != _impl->options.protocol || host.empty() ||
        !uri.getUserInfo().empty() || !uri.getFragment().empty())
        return AttemptResult::permanent(
            "http-endpoint-invalid",
            "Endpoint scheme, host, user information, or fragment is invalid");
    if (!_impl->allowedHost(host))
        return AttemptResult::permanent(
            "http-host-denied", "Endpoint host is not in the Provider allowlist");
    if (uri.getPort() == 0 || !_impl->allowedPort(uri.getPort()))
        return AttemptResult::permanent(
            "http-port-denied", "Endpoint port is not in the Provider allowlist");
    bool ambiguousAuthorization = false;
    bool unavailableAuthorization = false;
    const auto authorization = _impl->authorizationFor(
        request.attempt, host, uri.getPort(), ambiguousAuthorization,
        unavailableAuthorization);
    if (ambiguousAuthorization)
        return AttemptResult::permanent(
            "http-credential-binding-ambiguous",
            "Multiple equally specific authorization credentials match this target");
    if (unavailableAuthorization)
        return AttemptResult::permanent(
            "http-credential-reload-failed",
            "The target-bound credential file failed validation during reload");
    if (_impl->options.requireAuthorizationMatch && !authorization)
        return AttemptResult::permanent(
            "http-credential-binding-missing",
            "No authorization credential is bound to this service, operation, host, and port");

    std::map<std::string, std::string> forwarded;
    for (const auto& [key, value] : request.input->metadata)
    {
        const auto normalized = lower(key);
        if (normalized != "content-type" && normalized != "accept" &&
            normalized != "traceparent" && normalized != "tracestate")
            return AttemptResult::permanent(
                "http-metadata-denied",
                "HTTP Provider metadata key is not forwardable: " + key);
        if (!headerValue(value, 1024))
            return AttemptResult::permanent(
                "http-metadata-invalid", "HTTP Provider metadata value is invalid");
        if (forwarded.count(normalized) != 0)
            return AttemptResult::permanent(
                "http-metadata-invalid",
                "HTTP Provider metadata contains a duplicate header name");
        forwarded[normalized] = value;
    }

    std::vector<Poco::Net::IPAddress> addresses;
    Poco::Net::IPAddress literal;
    if (Poco::Net::IPAddress::tryParse(host, literal))
        addresses.push_back(std::move(literal));
    else
    {
        try
        {
            addresses = Poco::Net::DNS::resolve(host).addresses();
        }
        catch (const Poco::Exception& exception)
        {
            return AttemptResult::retryable(
                "http-dns-failure", exception.displayText());
        }
    }
    if (addresses.empty())
        return AttemptResult::retryable(
            "http-dns-failure", "Endpoint host resolved to no addresses");
    for (const auto& address : addresses)
    {
        if (const auto issue = addressPolicyIssue(address, _impl->options))
            return AttemptResult::permanent(
                "http-address-denied", *issue + ": " + address.toString());
    }
    if (request.cancellationRequested && request.cancellationRequested())
        return AttemptResult::permanent(
            "cancelled", "HTTP invocation was cancelled after DNS resolution", true);

    const auto timeout = std::max(std::chrono::milliseconds(1),
        std::min(request.attempt.remaining, _impl->options.maximumTimeout));
    const auto nowUnixMicroseconds = Poco::Timestamp().epochMicroseconds();
    const auto localDeadline = nowUnixMicroseconds +
        std::chrono::duration_cast<std::chrono::microseconds>(timeout).count();
    const auto effectiveDeadline = request.deadlineUnixMicroseconds > 0
        ? std::min(request.deadlineUnixMicroseconds, localDeadline)
        : localDeadline;
    try
    {
        auto session = _impl->session(uri, addresses.front(), timeout);
        Poco::Net::HTTPRequest outgoing(
            Poco::Net::HTTPRequest::HTTP_POST,
            uri.getPathEtc().empty() ? "/" : uri.getPathEtc(),
            Poco::Net::HTTPMessage::HTTP_1_1);
        outgoing.setHost(host, uri.getPort());
        outgoing.setContentLength64(
            static_cast<Poco::Int64>(request.input->payload.size()));
        outgoing.set("User-Agent", "PocoDDSRuntime-ServiceClient/1.0");
        outgoing.set("X-PDR-Service",
                     request.attempt.instance.advertisement.serviceName);
        outgoing.set("X-PDR-Operation", request.attempt.operation);
        outgoing.set("X-PDR-Attempt", std::to_string(request.attempt.attempt));
        outgoing.set("X-PDR-Invocation-Id", request.invocationId);
        outgoing.set("X-PDR-Timeout-Milliseconds",
                     std::to_string(timeout.count()));
        outgoing.set("X-PDR-Deadline-Unix-Microseconds",
                     std::to_string(effectiveDeadline));
        if (!request.attempt.idempotencyKey.empty())
            outgoing.set("Idempotency-Key", request.attempt.idempotencyKey);
        if (authorization) outgoing.set("Authorization", *authorization);
        for (const auto& [key, value] : forwarded) outgoing.set(key, value);

        auto& output = session->sendRequest(outgoing);
        if (!request.input->payload.empty())
            output.write(
                reinterpret_cast<const char*>(request.input->payload.data()),
                static_cast<std::streamsize>(request.input->payload.size()));
        output.flush();

        Poco::Net::HTTPResponse response;
        auto& input = session->receiveResponse(response);
        const auto length = response.getContentLength64();
        if (length >= 0 &&
            static_cast<Poco::UInt64>(length) >
                static_cast<Poco::UInt64>(_impl->options.maximumResponseBytes))
        {
            session->abort();
            return AttemptResult::permanent(
                "http-response-too-large",
                "HTTP response Content-Length exceeds Provider capacity", true);
        }

        std::vector<std::uint8_t> body;
        if (length > 0)
            body.reserve(static_cast<std::size_t>(length));
        std::array<char, 8192> buffer{};
        while (input.good())
        {
            if (request.cancellationRequested && request.cancellationRequested())
            {
                session->abort();
                return AttemptResult::permanent(
                    "cancelled", "HTTP invocation was cancelled while reading", true);
            }
            input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
            const auto count = input.gcount();
            if (count <= 0) break;
            if (static_cast<std::size_t>(count) >
                _impl->options.maximumResponseBytes - body.size())
            {
                session->abort();
                return AttemptResult::permanent(
                    "http-response-too-large",
                    "HTTP response body exceeds Provider capacity", true);
            }
            body.insert(body.end(), buffer.begin(), buffer.begin() + count);
        }

        const auto status = static_cast<int>(response.getStatus());
        if (status >= 200 && status < 300)
            return AttemptResult::success(std::move(body));
        if (retryableStatus(status))
            return AttemptResult::retryable(
                "http-retryable-status", statusDetail(status));
        if (status >= 300 && status < 400)
            return AttemptResult::permanent(
                "http-redirect-rejected", statusDetail(status), true);
        return AttemptResult::permanent(
            "http-permanent-status", statusDetail(status), true);
    }
    catch (const Poco::TimeoutException& exception)
    {
        return AttemptResult::retryable(
            "http-timeout", exception.displayText());
    }
    catch (const Poco::Net::SSLException& exception)
    {
        return AttemptResult::retryable(
            "http-tls-failure", exception.displayText());
    }
    catch (const Poco::Exception& exception)
    {
        return AttemptResult::retryable(
            "http-transport-failure", exception.displayText());
    }
    catch (const std::exception& exception)
    {
        return AttemptResult::retryable(
            "http-provider-failure", exception.what());
    }
}
} // namespace PocoDDS::ServiceClient
