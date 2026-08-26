#include "PocoDDS/BundleManagement/BundleRepositoryAuthorization.h"
#include "PocoDDS/BundleManagement/BundleDeploymentCoordinator.h"
#include "PocoDDS/BundleManagement/BundleRepositoryFingerprint.h"
#include "PocoDDS/BundleManagement/BundleRepositoryRolloutGuard.h"
#include "PocoDDS/Security/DetachedSignatureVerifier.h"

#include "Poco/DateTimeFormat.h"
#include "Poco/DateTimeFormatter.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/FileStream.h"
#include "Poco/Path.h"
#include "Poco/Timestamp.h"

#include <openssl/evp.h>
#include <openssl/pem.h>

#include <iostream>
#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace
{
using Key = std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)>;

Poco::Path child(const Poco::Path& directory, const std::string& name)
{
    Poco::Path result(directory);
    result.makeDirectory();
    result.setFileName(name);
    return result;
}

void write(const Poco::Path& path, const std::string& value)
{
    Poco::File(path.parent()).createDirectories();
    Poco::FileOutputStream output(path.toString(), std::ios::out | std::ios::trunc);
    output << value;
}

Key generateKey()
{
    std::unique_ptr<EVP_PKEY_CTX, decltype(&EVP_PKEY_CTX_free)> context(
        EVP_PKEY_CTX_new_id(EVP_PKEY_ED25519, nullptr), EVP_PKEY_CTX_free);
    EVP_PKEY* value = nullptr;
    if (!context || EVP_PKEY_keygen_init(context.get()) != 1 ||
        EVP_PKEY_keygen(context.get(), &value) != 1)
        throw Poco::SystemException("Cannot generate Ed25519 test key");
    return {value, EVP_PKEY_free};
}

void writePublicKey(const Poco::Path& path, EVP_PKEY* key)
{
    std::unique_ptr<BIO, decltype(&BIO_free)> output(BIO_new_file(path.toString().c_str(), "wb"),
                                                     BIO_free);
    if (!output || PEM_write_bio_PUBKEY(output.get(), key) != 1)
        throw Poco::WriteFileException("Cannot write Ed25519 test public key", path.toString());
}

std::string base64(const std::vector<unsigned char>& value)
{
    std::string encoded(((value.size() + 2) / 3) * 4, '\0');
    const int size = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(encoded.data()),
                                     value.data(), static_cast<int>(value.size()));
    encoded.resize(static_cast<std::size_t>(size));
    return encoded;
}

std::string sign(EVP_PKEY* key, const std::string& payload)
{
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(
        EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestSignInit(context.get(), nullptr, nullptr, nullptr, key) != 1)
        throw Poco::SystemException("Cannot initialize Ed25519 test signing");
    std::size_t size = 0;
    if (EVP_DigestSign(context.get(), nullptr, &size,
                       reinterpret_cast<const unsigned char*>(payload.data()), payload.size()) != 1)
        throw Poco::SystemException("Cannot size Ed25519 test signature");
    std::vector<unsigned char> signature(size);
    if (EVP_DigestSign(context.get(), signature.data(), &size,
                       reinterpret_cast<const unsigned char*>(payload.data()), payload.size()) != 1)
        throw Poco::SystemException("Cannot create Ed25519 test signature");
    signature.resize(size);
    return base64(signature);
}

std::string attestation(const std::string& publisher, const std::string& repository,
                        const std::string& digest, std::uint64_t rolloutSequence,
                        const std::string& releaseManifestSha256,
                        const std::string& sbomSha256)
{
    return "{\n  \"schemaVersion\": 2,\n  \"product\": \"PocoDDSBundleRepository\",\n"
           "  \"publisherId\": \"" + publisher + "\",\n  \"repositoryId\": \"" + repository +
           "\",\n  \"rolloutSequence\": " + std::to_string(rolloutSequence) +
           ",\n  \"candidateDigest\": \"" + digest +
           "\",\n  \"provenance\": {\n"
           "    \"releaseManifestSha256\": \"" + releaseManifestSha256 +
           "\",\n    \"sbomSha256\": \"" + sbomSha256 +
           "\",\n    \"version\": \"0.1.0\",\n"
           "    \"gitCommit\": \"" + std::string(40, 'e') +
           "\",\n    \"builderId\": \"test-builder\",\n"
           "    \"buildProfile\": \"server\",\n"
           "    \"artifactSetSha256\": \"" + std::string(64, 'd') +
           "\"\n  },\n  \"issuedAt\": \"" +
           Poco::DateTimeFormatter::format(Poco::Timestamp(),
                                           Poco::DateTimeFormat::ISO8601_FRAC_FORMAT) +
           "\"\n}\n";
}

void writeEvidence(const Poco::Path& evidence, const std::string& digest,
                   const std::string& publisher, const std::string& repository,
                   const std::string& keyId, EVP_PKEY* key,
                   std::uint64_t rolloutSequence = 1)
{
    const std::string sbom =
        "{\"spdxVersion\":\"SPDX-2.3\",\"documentNamespace\":"
        "\"https://pocodds.local/spdx/test\",\"packages\":[{\"name\":"
        "\"PocoDDSRuntime\",\"versionInfo\":\"0.1.0\"}]}\n";
    const Poco::Path sbomPath = child(evidence, digest + ".spdx.json");
    write(sbomPath, sbom);
    const std::string sbomDigest = PocoDDS::Security::sha256File(sbomPath.toString());
    const std::string releaseManifest =
        "{\"schemaVersion\":1,\"product\":\"PocoDDSRuntime\","
        "\"version\":\"0.1.0\",\"gitCommit\":\"" + std::string(40, 'e') +
        "\",\"dirty\":false,\"generatedAt\":\"2026-08-25T00:00:00Z\","
        "\"files\":[{\"path\":\"bundles/test.bndl\",\"size\":1,"
        "\"sha256\":\"" + std::string(64, 'a') + "\"}],\"sbom\":{\"path\":"
        "\"pocoddsruntime.spdx.json\",\"sha256\":\"" + sbomDigest +
        "\",\"spdxVersion\":\"SPDX-2.3\",\"documentNamespace\":"
        "\"https://pocodds.local/spdx/test\"},\"provenance\":{"
        "\"builderId\":\"test-builder\",\"buildProfile\":\"server\","
        "\"artifactSetSha256\":\"" + std::string(64, 'd') +
        "\",\"source\":{\"gitCommit\":\"" + std::string(40, 'e') +
        "\",\"dirty\":false}}}\n";
    const Poco::Path releaseManifestPath =
        child(evidence, digest + ".release-manifest.json");
    write(releaseManifestPath, releaseManifest);
    const std::string releaseManifestDigest =
        PocoDDS::Security::sha256File(releaseManifestPath.toString());
    const std::string payload = attestation(
        publisher, repository, digest, rolloutSequence,
        releaseManifestDigest, sbomDigest);
    const Poco::Path attestationPath = child(evidence, digest + ".attestation.json");
    write(attestationPath, payload);
    const std::string payloadDigest =
        PocoDDS::Security::sha256File(attestationPath.toString());
    write(child(evidence, digest + ".sig.json"),
          "{\n  \"schemaVersion\": 1,\n  \"product\": \"PocoDDSBundleRepository\",\n"
          "  \"algorithm\": \"Ed25519\",\n  \"keyId\": \"" + keyId +
          "\",\n  \"manifestSha256\": \"" + payloadDigest +
          "\",\n  \"signature\": \"" + sign(key, payload) + "\"\n}\n");
}

std::string policy(const std::string& key1Id, const std::string& key1Digest,
                   const std::string& key2Id = std::string(),
                   const std::string& key2Digest = std::string(), bool revokeFirst = false)
{
    std::string publishers =
        "    {\"publisherId\":\"vendor\",\"keyId\":\"" + key1Id +
        "\",\"algorithm\":\"Ed25519\",\"publicKeySha256\":\"" + key1Digest +
        "\",\"repositoryPatterns\":[\"runtime-*\"]}";
    if (!key2Id.empty())
        publishers +=
            ",\n    {\"publisherId\":\"vendor\",\"keyId\":\"" + key2Id +
            "\",\"algorithm\":\"Ed25519\",\"publicKeySha256\":\"" + key2Digest +
            "\",\"repositoryPatterns\":[\"runtime-*\"]}";
    const std::string revoked = revokeFirst
        ? "[{\"keyId\":\"" + key1Id +
              "\",\"revokedAt\":\"2026-01-01T00:00:00Z\",\"reason\":\"rotation\"}]"
        : "[]";
    return "{\n  \"schemaVersion\":1,\n  \"product\":\"PocoDDSBundleRepository\",\n"
           "  \"policyId\":\"bundle-policy-v1\",\n  \"allowedPublishers\":[\n" + publishers +
           "\n  ],\n  \"revokedKeys\":" + revoked + "\n}\n";
}

bool rejected(const std::function<void()>& operation)
{
    try
    {
        operation();
        return false;
    }
    catch (const Poco::Exception&)
    {
        return true;
    }
}
} // namespace

int main()
{
    Poco::Path root(Poco::Path::temp());
    root.pushDirectory("pdr-bundle-authorization-" +
                       std::to_string(Poco::Timestamp().epochMicroseconds()));
    root.makeDirectory();
    Poco::Path repository(root); repository.pushDirectory("bundles"); repository.makeDirectory();
    Poco::Path evidence(root); evidence.pushDirectory("evidence"); evidence.makeDirectory();
    Poco::Path keys(root); keys.pushDirectory("keys"); keys.makeDirectory();
    Poco::File(repository).createDirectories();
    Poco::File(evidence).createDirectories();
    Poco::File(keys).createDirectories();
    write(child(repository, "bundle.bndl"), "authorized-candidate");

    try
    {
        const std::string digest = PocoDDS::BundleManagement::BundleRepositoryFingerprint::
            calculateDirectory(repository.toString());
        const Key first = generateKey();
        const Key second = generateKey();
        const Poco::Path firstPublic = child(keys, "vendor-2026.pem");
        const Poco::Path secondPublic = child(keys, "vendor-2027.pem");
        writePublicKey(firstPublic, first.get());
        writePublicKey(secondPublic, second.get());
        const std::string firstDigest = PocoDDS::Security::sha256File(firstPublic.toString());
        const std::string secondDigest = PocoDDS::Security::sha256File(secondPublic.toString());
        const Poco::Path policyPath = child(root, "bundle-trust-policy.json");
        write(policyPath, policy("vendor-2026", firstDigest));

        PocoDDS::BundleManagement::BundleRepositoryAuthorizationOptions options;
        options.required = true;
        options.repositoryId = "runtime-main";
        options.evidenceDirectory = evidence.toString();
        options.trustPolicyFile = policyPath.toString();
        options.expectedTrustPolicyId = "bundle-policy-v1";
        options.expectedTrustPolicySha256 = PocoDDS::Security::sha256File(policyPath.toString());
        options.trustedKeysDirectory = keys.toString();

        writeEvidence(evidence, digest, "vendor", options.repositoryId,
                      "vendor-2026", first.get());
        const auto verified = PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
            repository.toString(), digest, options);
        if (!verified.verified || verified.publisherId != "vendor" ||
            verified.keyId != "vendor-2026" || verified.rolloutSequence != 1 ||
            verified.releaseVersion != "0.1.0" ||
            verified.gitCommit != std::string(40, 'e') ||
            verified.builderId != "test-builder" || verified.buildProfile != "server")
            return 1;

        // Prove that an authorized deployment keeps an exact, still-verifiable
        // previous generation and can restore it before advancing high-water.
        Poco::Path state(root); state.pushDirectory("state"); state.makeDirectory();
        Poco::Path lkg(state); lkg.pushDirectory("last-known-good"); lkg.makeDirectory();
        Poco::File(state).createDirectories();
        Poco::File(lkg).createDirectories();
        write(child(lkg, "bundle.bndl"), "authorized-candidate");
        PocoDDS::BundleManagement::BundleRepositoryRolloutGuard::commitCandidate(
            state.toString(), digest, verified);

        write(child(repository, "bundle.bndl"), "authorized-candidate-v2");
        const std::string candidateDigest =
            PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(
                repository.toString());
        writeEvidence(evidence, candidateDigest, "vendor", options.repositoryId,
                      "vendor-2026", first.get(), 2);
        const auto candidateAuthorization =
            PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                repository.toString(), candidateDigest, options);
        write(child(state, "transaction.properties"),
              "transactionId=tx-signed-rollback\nstate=restartRequired\n"
              "candidateDigest=" + candidateDigest +
              "\nauthorizationVerified=true\nrepositoryId=" +
              candidateAuthorization.repositoryId + "\npublisherId=" +
              candidateAuthorization.publisherId + "\nsigningKeyId=" +
              candidateAuthorization.keyId + "\ntrustPolicyId=" +
              candidateAuthorization.policyId + "\ntrustPolicySha256=" +
              candidateAuthorization.policySha256 + "\nattestationSha256=" +
              candidateAuthorization.attestationSha256 + "\nrolloutSequence=" +
              std::to_string(candidateAuthorization.rolloutSequence) +
              "\nreleaseManifestSha256=" + candidateAuthorization.releaseManifestSha256 +
              "\nsbomSha256=" + candidateAuthorization.sbomSha256 +
              "\nartifactSetSha256=" + candidateAuthorization.artifactSetSha256 +
              "\nreleaseVersion=" + candidateAuthorization.releaseVersion +
              "\ngitCommit=" + candidateAuthorization.gitCommit +
              "\nbuilderId=" + candidateAuthorization.builderId +
              "\nbuildProfile=" + candidateAuthorization.buildProfile + "\nerror=\n");
        PocoDDS::BundleManagement::BundleDeploymentOptions deploymentOptions;
        deploymentOptions.repositoryDirectory = repository.toString();
        deploymentOptions.stateDirectory = state.toString();
        deploymentOptions.authorization = options;
        PocoDDS::BundleManagement::BundleDeploymentCoordinator coordinator(
            deploymentOptions);
        if (coordinator.beginActivation() != "tx-signed-rollback") return 20;
        coordinator.rollback("tx-signed-rollback", "fault injection");
        const std::string restoredDigest =
            PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(
                repository.toString());
        if (restoredDigest != digest || coordinator.status().state != "rolledBack")
            return 21;
        const auto restored = PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
            repository.toString(), restoredDigest, options);
        PocoDDS::BundleManagement::BundleRepositoryRolloutGuard::verifyCandidate(
            state.toString(), restoredDigest, restored);
        if (restored.rolloutSequence != 1) return 22;

        write(child(evidence, digest + ".spdx.json"), "{\"tampered\":true}\n");
        if (!rejected([&] {
                PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                    repository.toString(), digest, options);
            })) return 23;
        writeEvidence(evidence, digest, "vendor", options.repositoryId,
                      "vendor-2026", first.get());

        Poco::File(child(evidence, digest + ".sig.json")).remove();
        if (!rejected([&] {
                PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                    repository.toString(), digest, options);
            })) return 2;

        writeEvidence(evidence, digest, "rogue", options.repositoryId,
                      "vendor-2026", first.get());
        if (!rejected([&] {
                PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                    repository.toString(), digest, options);
            })) return 3;

        writeEvidence(evidence, digest, "vendor", options.repositoryId,
                      "vendor-2026", first.get());
        write(child(repository, "bundle.bndl"), "tampered-after-signing");
        const std::string tamperedDigest =
            PocoDDS::BundleManagement::BundleRepositoryFingerprint::calculateDirectory(
                repository.toString());
        if (!rejected([&] {
                PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                    repository.toString(), tamperedDigest, options);
            })) return 4;
        write(child(repository, "bundle.bndl"), "authorized-candidate");

        write(policyPath, policy("vendor-2026", firstDigest, {}, {}, true));
        options.expectedTrustPolicySha256 = PocoDDS::Security::sha256File(policyPath.toString());
        if (!rejected([&] {
                PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
                    repository.toString(), digest, options);
            })) return 5;

        write(policyPath, policy("vendor-2026", firstDigest, "vendor-2027", secondDigest, true));
        options.expectedTrustPolicySha256 = PocoDDS::Security::sha256File(policyPath.toString());
        writeEvidence(evidence, digest, "vendor", options.repositoryId,
                      "vendor-2027", second.get());
        const auto rotated = PocoDDS::BundleManagement::BundleRepositoryAuthorization::verify(
            repository.toString(), digest, options);
        if (!rotated.verified || rotated.keyId != "vendor-2027")
            return 6;

        Poco::File(root).remove(true);
        std::cout << "BUNDLE_REPOSITORY_AUTHORIZATION_PASS signed=1 unsignedRejected=1 "
                     "publisherRejected=1 tamperRejected=1 revokedRejected=1 rotation=1 "
                     "signedRollback=1 provenanceTamperRejected=1\n";
        return 0;
    }
    catch (const Poco::Exception& error)
    {
        std::cerr << error.displayText() << '\n';
        if (Poco::File(root).exists()) Poco::File(root).remove(true);
        return 10;
    }
}
