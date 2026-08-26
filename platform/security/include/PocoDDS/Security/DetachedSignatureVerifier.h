#pragma once

#include <string>

namespace PocoDDS::Security
{
struct DetachedSignatureEvidence
{
    std::string algorithm;
    std::string keyId;
    std::string product;
    std::string payloadSha256;
    std::string publicKeySha256;
};

/// Verifies a versioned JSON signature envelope over the exact payload bytes.
/// The public key must be an Ed25519 PEM key supplied by the current trusted
/// installation, never by the unverified payload being checked.
DetachedSignatureEvidence verifyEd25519DetachedSignature(
    const std::string& payloadPath,
    const std::string& signatureEnvelopePath,
    const std::string& publicKeyPath,
    const std::string& expectedKeyId,
    const std::string& expectedProduct);

std::string sha256File(const std::string& path);
} // namespace PocoDDS::Security
