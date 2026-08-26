#include "PocoDDS/Security/DetachedSignatureVerifier.h"

#include "Poco/DigestEngine.h"
#include "Poco/Exception.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/SHA2Engine.h"

#include <openssl/evp.h>
#include <openssl/pem.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <memory>
#include <vector>

namespace PocoDDS::Security
{
namespace
{
using Bytes = std::vector<unsigned char>;

Bytes readBytes(const std::string& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw Poco::OpenFileException("Cannot open signed material", path);
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

std::string sha256(const Bytes& content)
{
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    if (!content.empty())
        engine.update(reinterpret_cast<const char*>(content.data()), content.size());
    return Poco::DigestEngine::digestToHex(engine.digest());
}

Bytes decodeBase64(std::string value)
{
    value.erase(std::remove_if(value.begin(), value.end(), [](unsigned char character) {
        return std::isspace(character) != 0;
    }), value.end());
    if (value.empty() || value.size() % 4 != 0)
        throw Poco::DataFormatException("Detached signature is not valid Base64");
    Bytes decoded((value.size() / 4) * 3);
    const int result = EVP_DecodeBlock(
        decoded.data(), reinterpret_cast<const unsigned char*>(value.data()),
        static_cast<int>(value.size()));
    if (result < 0)
        throw Poco::DataFormatException("Detached signature is not valid Base64");
    std::size_t size = static_cast<std::size_t>(result);
    if (value.back() == '=') --size;
    if (value.size() > 1 && value[value.size() - 2] == '=') --size;
    decoded.resize(size);
    return decoded;
}

std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> readPublicKey(const std::string& path)
{
    std::unique_ptr<BIO, decltype(&BIO_free)> stream(BIO_new_file(path.c_str(), "rb"), BIO_free);
    if (!stream)
        throw Poco::OpenFileException("Cannot open Ed25519 public key", path);
    EVP_PKEY* key = PEM_read_bio_PUBKEY(stream.get(), nullptr, nullptr, nullptr);
    if (!key)
        throw Poco::DataFormatException("Cannot parse public key PEM", path);
    return {key, EVP_PKEY_free};
}
} // namespace

std::string sha256File(const std::string& path)
{
    return sha256(readBytes(path));
}

DetachedSignatureEvidence verifyEd25519DetachedSignature(
    const std::string& payloadPath,
    const std::string& signatureEnvelopePath,
    const std::string& publicKeyPath,
    const std::string& expectedKeyId,
    const std::string& expectedProduct)
{
    if (expectedKeyId.empty() || expectedProduct.empty())
        throw Poco::InvalidArgumentException(
            "Detached signature verification requires key and product identities");

    const Bytes payload = readBytes(payloadPath);
    const Bytes signatureDocument = readBytes(signatureEnvelopePath);
    Poco::JSON::Parser parser;
    const auto envelope = parser.parse(
        std::string(signatureDocument.begin(), signatureDocument.end()))
                              .extract<Poco::JSON::Object::Ptr>();
    if (envelope.isNull() || envelope->getValue<int>("schemaVersion") != 1 ||
        envelope->getValue<std::string>("product") != expectedProduct ||
        envelope->getValue<std::string>("algorithm") != "Ed25519")
        throw Poco::DataFormatException("unsupported detached signature envelope");

    const std::string keyId = envelope->getValue<std::string>("keyId");
    if (keyId != expectedKeyId)
        throw Poco::InvalidAccessException("detached signature key id is not trusted", keyId);
    const std::string payloadDigest = sha256(payload);
    if (envelope->getValue<std::string>("manifestSha256") != payloadDigest)
        throw Poco::DataFormatException("detached signature payload digest mismatch");

    const Bytes signature = decodeBase64(envelope->getValue<std::string>("signature"));
    const auto key = readPublicKey(publicKeyPath);
    if (EVP_PKEY_base_id(key.get()) != EVP_PKEY_ED25519)
        throw Poco::DataFormatException("public key is not Ed25519", publicKeyPath);
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(
        EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestVerifyInit(context.get(), nullptr, nullptr, nullptr, key.get()) != 1)
        throw Poco::SystemException("Cannot initialize Ed25519 verification");
    if (EVP_DigestVerify(context.get(), signature.data(), signature.size(),
                         payload.data(), payload.size()) != 1)
        throw Poco::InvalidAccessException("detached signature verification failed");

    return {"Ed25519", keyId, expectedProduct, payloadDigest, sha256File(publicKeyPath)};
}
} // namespace PocoDDS::Security
