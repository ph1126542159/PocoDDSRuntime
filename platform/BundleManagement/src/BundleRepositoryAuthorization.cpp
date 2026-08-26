#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"

#include "PocoDDS/Security/DetachedSignatureVerifier.h"

#include "Poco/DateTimeFormat.h"
#include "Poco/DateTimeParser.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/Path.h"
#include "Poco/String.h"
#include "Poco/Timestamp.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <limits>
#include <regex>
#include <sstream>
#include <vector>

namespace PocoDDS::BundleManagement
{
namespace
{
constexpr const char* PRODUCT = "PocoDDSBundleRepository";

std::string readText(const std::string& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw Poco::OpenFileException("Cannot open Bundle authorization material", path);
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

Poco::JSON::Object::Ptr parseObject(const std::string& path, const std::string& description)
{
    try
    {
        Poco::JSON::Parser parser;
        auto result = parser.parse(readText(path)).extract<Poco::JSON::Object::Ptr>();
        if (result.isNull())
            throw Poco::DataFormatException(description + " must be a JSON object", path);
        return result;
    }
    catch (const Poco::Exception&)
    {
        throw;
    }
    catch (const std::exception& error)
    {
        throw Poco::DataFormatException(description + " is malformed", error.what());
    }
}

bool isSha256(const std::string& value)
{
    return std::regex_match(value, std::regex("^[0-9a-f]{64}$"));
}

bool isGitCommit(const std::string& value)
{
    return std::regex_match(value, std::regex("^(?:[0-9a-f]{40}|[0-9a-f]{64})$"));
}

bool safeKeyId(const std::string& value)
{
    return std::regex_match(value, std::regex("^[A-Za-z0-9._-]+$"));
}

bool nonWhitespaceIdentity(const std::string& value)
{
    return !value.empty() && std::none_of(value.begin(), value.end(), [](unsigned char character) {
        return std::isspace(character) != 0 || std::iscntrl(character) != 0;
    });
}

std::string canonicalText(const std::string& value)
{
    std::filesystem::path path = std::filesystem::weakly_canonical(
        std::filesystem::absolute(std::filesystem::u8path(value)));
    std::string result = path.generic_u8string();
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::transform(result.begin(), result.end(), result.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
#endif
    while (result.size() > 1 && result.back() == '/') result.pop_back();
    return result;
}

bool sameOrChild(const std::string& parent, const std::string& candidate)
{
    return candidate == parent ||
           (candidate.size() > parent.size() && candidate.compare(0, parent.size(), parent) == 0 &&
            candidate[parent.size()] == '/');
}

void requireOutsideRepository(const std::string& repository, const std::string& path,
                              const std::string& description)
{
    const std::string repositoryPath = canonicalText(repository);
    const std::string candidatePath = canonicalText(path);
    if (sameOrChild(repositoryPath, candidatePath))
        throw Poco::InvalidArgumentException(
            description + " must not come from the unverified Bundle repository", path);
}

Poco::Timestamp parseTime(const std::string& value, const std::string& field)
{
    if (value.empty())
        throw Poco::DataFormatException("Bundle trust " + field + " must not be empty");
    try
    {
        int timeZoneDifferential = 0;
        return Poco::DateTimeParser::parse(
                   Poco::DateTimeFormat::ISO8601_FORMAT, value, timeZoneDifferential)
            .timestamp();
    }
    catch (const Poco::Exception& error)
    {
        throw Poco::DataFormatException("Bundle trust " + field + " is not valid ISO-8601",
                                        error.displayText());
    }
}

bool matchesPattern(const std::string& value, const std::string& pattern)
{
    const auto wildcard = pattern.find('*');
    if (wildcard == std::string::npos)
        return value == pattern;
    if (wildcard != pattern.size() - 1 || pattern.find('*', wildcard + 1) != std::string::npos)
        throw Poco::DataFormatException(
            "Bundle repository pattern may contain only one trailing wildcard", pattern);
    return value.compare(0, wildcard, pattern, 0, wildcard) == 0;
}

std::string evidencePath(const BundleRepositoryAuthorizationOptions& options,
                         const std::string& digest, const std::string& suffix)
{
    Poco::Path path(options.evidenceDirectory);
    path.makeDirectory();
    path.setFileName(digest + suffix);
    return path.toString();
}

std::string publicKeyPath(const BundleRepositoryAuthorizationOptions& options,
                          const std::string& keyId)
{
    if (!safeKeyId(keyId))
        throw Poco::DataFormatException("Bundle signing key id is not a safe file identity", keyId);
    Poco::Path path(options.trustedKeysDirectory);
    path.makeDirectory();
    path.setFileName(keyId + ".pem");
    return path.toString();
}

void validateOptions(const std::string& repositoryDirectory,
                     const BundleRepositoryAuthorizationOptions& options)
{
    if (!options.required)
        return;
    if (!nonWhitespaceIdentity(options.repositoryId) ||
        !nonWhitespaceIdentity(options.expectedTrustPolicyId) ||
        !isSha256(options.expectedTrustPolicySha256) || options.evidenceDirectory.empty() ||
        options.trustPolicyFile.empty() || options.trustedKeysDirectory.empty())
        throw Poco::InvalidArgumentException(
            "Required Bundle authorization needs repository identity, evidence, pinned policy and trusted keys");
    if (!Poco::File(repositoryDirectory).isDirectory())
        throw Poco::FileNotFoundException("Bundle repository directory", repositoryDirectory);
    if (!Poco::File(options.evidenceDirectory).isDirectory())
        throw Poco::FileNotFoundException("Bundle authorization evidence directory",
                                          options.evidenceDirectory);
    if (!Poco::File(options.trustedKeysDirectory).isDirectory())
        throw Poco::FileNotFoundException("Bundle trusted keys directory",
                                          options.trustedKeysDirectory);
    if (!Poco::File(options.trustPolicyFile).isFile())
        throw Poco::FileNotFoundException("Bundle trust policy", options.trustPolicyFile);
    requireOutsideRepository(repositoryDirectory, options.evidenceDirectory,
                             "Bundle authorization evidence");
    requireOutsideRepository(repositoryDirectory, options.trustPolicyFile,
                             "Bundle trust policy");
    requireOutsideRepository(repositoryDirectory, options.trustedKeysDirectory,
                             "Bundle trusted keys");
}
} // namespace

BundleRepositoryAuthorizationEvidence BundleRepositoryAuthorization::verify(
    const std::string& repositoryDirectory,
    const std::string& candidateDigest,
    const BundleRepositoryAuthorizationOptions& options)
{
    if (!options.required)
        return {};
    validateOptions(repositoryDirectory, options);
    if (!isSha256(candidateDigest))
        throw Poco::InvalidArgumentException(
            "Required Bundle authorization needs a deterministic candidate SHA-256");

    const std::string actualPolicyDigest =
        PocoDDS::Security::sha256File(options.trustPolicyFile);
    if (actualPolicyDigest != options.expectedTrustPolicySha256)
        throw Poco::InvalidAccessException("Bundle trust policy SHA-256 is not trusted");
    const auto policy = parseObject(options.trustPolicyFile, "Bundle trust policy");
    if (policy->getValue<int>("schemaVersion") != 1 ||
        policy->getValue<std::string>("product") != PRODUCT ||
        policy->getValue<std::string>("policyId") != options.expectedTrustPolicyId)
        throw Poco::DataFormatException("Unsupported or unexpected Bundle trust policy");

    const std::string attestationFile =
        evidencePath(options, candidateDigest, ".attestation.json");
    const std::string signatureFile = evidencePath(options, candidateDigest, ".sig.json");
    const Poco::File attestationMaterial(attestationFile);
    const Poco::File signatureMaterial(signatureFile);
    if (!attestationMaterial.exists() || !attestationMaterial.isFile() ||
        !signatureMaterial.exists() || !signatureMaterial.isFile())
        throw Poco::InvalidAccessException(
            "Signed Bundle repository requires digest-bound attestation and signature",
            candidateDigest);
    const auto attestation = parseObject(attestationFile, "Bundle repository attestation");
    if (attestation->getValue<int>("schemaVersion") != 2 ||
        attestation->getValue<std::string>("product") != PRODUCT ||
        attestation->getValue<std::string>("repositoryId") != options.repositoryId ||
        attestation->getValue<std::string>("candidateDigest") != candidateDigest)
        throw Poco::DataFormatException(
            "Bundle repository attestation does not match repository identity and digest");
    const std::string publisherId = attestation->getValue<std::string>("publisherId");
    if (!nonWhitespaceIdentity(publisherId))
        throw Poco::DataFormatException("Bundle publisher id is malformed");
    const auto rolloutSequence = attestation->getValue<Poco::UInt64>("rolloutSequence");
    if (rolloutSequence == 0 ||
        rolloutSequence > static_cast<Poco::UInt64>(std::numeric_limits<std::int64_t>::max()))
        throw Poco::DataFormatException(
            "Bundle rollout sequence is outside the supported positive 63-bit range");
    const auto provenance = attestation->getObject("provenance");
    if (provenance.isNull())
        throw Poco::DataFormatException(
            "Bundle repository attestation lacks release provenance");
    const std::string releaseManifestSha256 =
        provenance->getValue<std::string>("releaseManifestSha256");
    const std::string sbomSha256 = provenance->getValue<std::string>("sbomSha256");
    const std::string artifactSetSha256 =
        provenance->getValue<std::string>("artifactSetSha256");
    const std::string releaseVersion = provenance->getValue<std::string>("version");
    const std::string gitCommit = provenance->getValue<std::string>("gitCommit");
    const std::string builderId = provenance->getValue<std::string>("builderId");
    const std::string buildProfile = provenance->getValue<std::string>("buildProfile");
    if (!isSha256(releaseManifestSha256) || !isSha256(sbomSha256) ||
        !isSha256(artifactSetSha256) || !nonWhitespaceIdentity(releaseVersion) ||
        !isGitCommit(gitCommit) || !nonWhitespaceIdentity(builderId) ||
        !nonWhitespaceIdentity(buildProfile))
        throw Poco::DataFormatException(
            "Bundle repository release provenance is malformed");

    const std::string releaseManifestFile =
        evidencePath(options, candidateDigest, ".release-manifest.json");
    const std::string sbomFile = evidencePath(options, candidateDigest, ".spdx.json");
    if (!Poco::File(releaseManifestFile).isFile() || !Poco::File(sbomFile).isFile())
        throw Poco::InvalidAccessException(
            "Signed Bundle repository requires bound release manifest and SPDX SBOM",
            candidateDigest);
    if (PocoDDS::Security::sha256File(releaseManifestFile) != releaseManifestSha256 ||
        PocoDDS::Security::sha256File(sbomFile) != sbomSha256)
        throw Poco::InvalidAccessException(
            "Bundle release provenance digest does not match bound evidence");
    const auto releaseManifest = parseObject(releaseManifestFile, "Bundle release manifest");
    const auto releaseProvenance = releaseManifest->getObject("provenance");
    const auto releaseSbom = releaseManifest->getObject("sbom");
    const auto releaseFiles = releaseManifest->getArray("files");
    const auto releaseSource = releaseProvenance.isNull()
        ? Poco::JSON::Object::Ptr() : releaseProvenance->getObject("source");
    parseTime(releaseManifest->getValue<std::string>("generatedAt"),
              "release manifest generatedAt");
    if (releaseManifest->getValue<int>("schemaVersion") != 1 ||
        releaseManifest->getValue<std::string>("product") != "PocoDDSRuntime" ||
        releaseManifest->getValue<std::string>("version") != releaseVersion ||
        Poco::toLower(releaseManifest->getValue<std::string>("gitCommit")) != gitCommit ||
        releaseManifest->getValue<bool>("dirty") || releaseProvenance.isNull() ||
        releaseSbom.isNull() || releaseSource.isNull() || releaseFiles.isNull() ||
        releaseFiles->empty() ||
        releaseProvenance->getValue<std::string>("artifactSetSha256") !=
            artifactSetSha256 ||
        releaseProvenance->getValue<std::string>("builderId") != builderId ||
        releaseProvenance->getValue<std::string>("buildProfile") != buildProfile ||
        Poco::toLower(releaseSource->getValue<std::string>("gitCommit")) != gitCommit ||
        releaseSource->getValue<bool>("dirty") ||
        releaseSbom->getValue<std::string>("sha256") != sbomSha256 ||
        releaseSbom->getValue<std::string>("spdxVersion") != "SPDX-2.3")
        throw Poco::DataFormatException(
            "Bundle release manifest identity does not match signed provenance");
    const auto sbom = parseObject(sbomFile, "Bundle SPDX SBOM");
    const auto packages = sbom->getArray("packages");
    if (sbom->getValue<std::string>("spdxVersion") != "SPDX-2.3" ||
        sbom->getValue<std::string>("documentNamespace") !=
            releaseSbom->getValue<std::string>("documentNamespace") ||
        packages.isNull())
        throw Poco::DataFormatException("Bundle release SBOM is malformed");
    bool runtimePackageFound = false;
    for (std::size_t index = 0; index < packages->size(); ++index)
    {
        const auto package = packages->getObject(static_cast<unsigned int>(index));
        runtimePackageFound = runtimePackageFound ||
            (!package.isNull() && package->optValue<std::string>("name", "") ==
                                      "PocoDDSRuntime" &&
             package->optValue<std::string>("versionInfo", "") == releaseVersion);
    }
    if (!runtimePackageFound)
        throw Poco::DataFormatException(
            "Bundle release SBOM does not identify the Runtime version");
    const Poco::Timestamp issuedAt =
        parseTime(attestation->getValue<std::string>("issuedAt"), "attestation issuedAt");
    const Poco::Timestamp current;
    if (issuedAt.epochMicroseconds() > current.epochMicroseconds() + 300000000)
        throw Poco::InvalidAccessException("Bundle attestation issue time is in the future");

    const auto signature = parseObject(signatureFile, "Bundle repository signature");
    if (signature->getValue<int>("schemaVersion") != 1 ||
        signature->getValue<std::string>("product") != PRODUCT ||
        signature->getValue<std::string>("algorithm") != "Ed25519")
        throw Poco::DataFormatException("Unsupported Bundle repository signature envelope");
    const std::string keyId = signature->getValue<std::string>("keyId");
    if (!safeKeyId(keyId))
        throw Poco::DataFormatException("Bundle signing key id is malformed", keyId);

    const auto revoked = policy->getArray("revokedKeys");
    if (revoked.isNull())
        throw Poco::DataFormatException("Bundle trust policy revocation list is malformed");
    for (std::size_t index = 0; index < revoked->size(); ++index)
    {
        const auto entry = revoked->getObject(static_cast<unsigned int>(index));
        if (entry.isNull() || !entry->has("keyId") || !entry->has("revokedAt") ||
            !entry->has("reason") || entry->getValue<std::string>("reason").empty())
            throw Poco::DataFormatException("Bundle trust policy revocation entry is malformed");
        parseTime(entry->getValue<std::string>("revokedAt"), "revokedAt");
        if (entry->getValue<std::string>("keyId") == keyId)
            throw Poco::InvalidAccessException(
                "Bundle signing key is revoked",
                keyId + ": " + entry->getValue<std::string>("reason"));
    }

    const auto publishers = policy->getArray("allowedPublishers");
    if (publishers.isNull())
        throw Poco::DataFormatException("Bundle trust policy publisher list is malformed");
    std::vector<Poco::JSON::Object::Ptr> matches;
    for (std::size_t index = 0; index < publishers->size(); ++index)
    {
        const auto entry = publishers->getObject(static_cast<unsigned int>(index));
        if (!entry.isNull() && entry->getValue<std::string>("publisherId") == publisherId &&
            entry->getValue<std::string>("keyId") == keyId)
            matches.push_back(entry);
    }
    if (matches.size() != 1)
        throw Poco::InvalidAccessException(
            "Bundle publisher and signing key are not uniquely allowed");
    const auto publisher = matches.front();
    if (publisher->getValue<std::string>("algorithm") != "Ed25519")
        throw Poco::DataFormatException("Bundle publisher algorithm is not Ed25519");
    const auto patterns = publisher->getArray("repositoryPatterns");
    if (patterns.isNull() || patterns->empty())
        throw Poco::DataFormatException("Bundle publisher repository patterns are malformed");
    bool repositoryAllowed = false;
    for (std::size_t index = 0; index < patterns->size(); ++index)
    {
        const std::string pattern = patterns->getElement<std::string>(
            static_cast<unsigned int>(index));
        repositoryAllowed = repositoryAllowed || matchesPattern(options.repositoryId, pattern);
    }
    if (!repositoryAllowed)
        throw Poco::InvalidAccessException(
            "Bundle publisher is not allowed for this repository identity",
            options.repositoryId);

    const std::string keyFile = publicKeyPath(options, keyId);
    const Poco::File trustedKey(keyFile);
    if (!trustedKey.exists() || !trustedKey.isFile())
        throw Poco::FileNotFoundException("Trusted Bundle public key", keyFile);
    const std::string publicKeyDigest = PocoDDS::Security::sha256File(keyFile);
    if (publisher->getValue<std::string>("publicKeySha256") != publicKeyDigest)
        throw Poco::InvalidAccessException("Bundle public key is not allowed by trust policy");

    Poco::Timestamp notBefore(0);
    Poco::Timestamp notAfter(0);
    const bool hasNotBefore = publisher->has("notBefore");
    const bool hasNotAfter = publisher->has("notAfter");
    if (hasNotBefore)
        notBefore = parseTime(publisher->getValue<std::string>("notBefore"), "notBefore");
    if (hasNotAfter)
        notAfter = parseTime(publisher->getValue<std::string>("notAfter"), "notAfter");
    if (hasNotBefore && hasNotAfter &&
        notBefore.epochMicroseconds() >= notAfter.epochMicroseconds())
        throw Poco::DataFormatException("Bundle publisher validity window is invalid");
    if (hasNotBefore && (current < notBefore || issuedAt < notBefore))
        throw Poco::InvalidAccessException("Bundle publisher key is not active yet");
    if (hasNotAfter && (current >= notAfter || issuedAt >= notAfter))
        throw Poco::InvalidAccessException("Bundle publisher key has expired");

    const auto signatureEvidence = PocoDDS::Security::verifyEd25519DetachedSignature(
        attestationFile, signatureFile, keyFile, keyId, PRODUCT);
    BundleRepositoryAuthorizationEvidence result;
    result.verified = true;
    result.repositoryId = options.repositoryId;
    result.publisherId = publisherId;
    result.keyId = keyId;
    result.policyId = options.expectedTrustPolicyId;
    result.policySha256 = actualPolicyDigest;
    result.attestationSha256 = signatureEvidence.payloadSha256;
    result.rolloutSequence = static_cast<std::uint64_t>(rolloutSequence);
    result.releaseManifestSha256 = releaseManifestSha256;
    result.sbomSha256 = sbomSha256;
    result.artifactSetSha256 = artifactSetSha256;
    result.releaseVersion = releaseVersion;
    result.gitCommit = gitCommit;
    result.builderId = builderId;
    result.buildProfile = buildProfile;
    return result;
}
} // namespace PocoDDS::BundleManagement
