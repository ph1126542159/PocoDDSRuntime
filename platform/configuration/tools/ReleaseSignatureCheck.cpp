#include <Poco/JSON/Object.h>
#include <Poco/JSON/Parser.h>
#include <Poco/Dynamic/Var.h>

#include <openssl/evp.h>
#include <openssl/pem.h>

#include <algorithm>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
std::vector<unsigned char> readBytes(const std::string& path)
{
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot open file: " + path);
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}

std::string sha256(const std::vector<unsigned char>& content)
{
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context.get(), content.data(), content.size()) != 1)
        throw std::runtime_error("cannot initialize SHA-256");
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int size = 0;
    if (EVP_DigestFinal_ex(context.get(), digest, &size) != 1)
        throw std::runtime_error("cannot finalize SHA-256");
    std::ostringstream value;
    value << std::hex << std::setfill('0');
    for (unsigned int index = 0; index < size; ++index) value << std::setw(2) << static_cast<int>(digest[index]);
    return value.str();
}

std::vector<unsigned char> decodeBase64(std::string value)
{
    value.erase(std::remove_if(value.begin(), value.end(), [](unsigned char character) {
        return std::isspace(character) != 0;
    }), value.end());
    if (value.empty() || value.size() % 4 != 0)
        throw std::runtime_error("signature is not valid Base64");
    std::vector<unsigned char> decoded((value.size() / 4) * 3);
    const int result = EVP_DecodeBlock(decoded.data(),
        reinterpret_cast<const unsigned char*>(value.data()), static_cast<int>(value.size()));
    if (result < 0) throw std::runtime_error("signature is not valid Base64");
    std::size_t size = static_cast<std::size_t>(result);
    if (!value.empty() && value.back() == '=') --size;
    if (value.size() > 1 && value[value.size() - 2] == '=') --size;
    decoded.resize(size);
    return decoded;
}

std::unique_ptr<EVP_PKEY, decltype(&EVP_PKEY_free)> readPublicKey(const std::string& path)
{
    std::unique_ptr<BIO, decltype(&BIO_free)> stream(BIO_new_file(path.c_str(), "rb"), BIO_free);
    if (!stream) throw std::runtime_error("cannot open public key: " + path);
    EVP_PKEY* key = PEM_read_bio_PUBKEY(stream.get(), nullptr, nullptr, nullptr);
    if (!key) throw std::runtime_error("cannot parse public key PEM");
    return {key, EVP_PKEY_free};
}
}

int main(int argc, char** argv)
{
    if (argc != 5 && argc != 6)
    {
        std::cerr << "usage: pdr-signature-check PAYLOAD SIGNATURE PUBLIC_KEY EXPECTED_KEY_ID [EXPECTED_PRODUCT]\n";
        return 2;
    }
    try
    {
        const auto manifest = readBytes(argv[1]);
        const auto signatureDocument = readBytes(argv[2]);
        Poco::JSON::Parser parser;
        const auto envelope = parser.parse(std::string(signatureDocument.begin(), signatureDocument.end()))
                                  .extract<Poco::JSON::Object::Ptr>();
        const std::string expectedProduct = argc == 6 ? argv[5] : "PocoDDSRuntime";
        if (envelope->getValue<int>("schemaVersion") != 1 ||
            envelope->getValue<std::string>("product") != expectedProduct ||
            envelope->getValue<std::string>("algorithm") != "Ed25519")
            throw std::runtime_error("unsupported release signature envelope");
        const std::string keyId = envelope->getValue<std::string>("keyId");
        if (keyId != argv[4]) throw std::runtime_error("release signature key id is not trusted");
        if (envelope->getValue<std::string>("manifestSha256") != sha256(manifest))
            throw std::runtime_error("release signature manifest digest mismatch");
        const auto signature = decodeBase64(envelope->getValue<std::string>("signature"));
        const auto key = readPublicKey(argv[3]);
        if (EVP_PKEY_base_id(key.get()) != EVP_PKEY_ED25519)
            throw std::runtime_error("public key is not Ed25519");
        std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(), EVP_MD_CTX_free);
        if (!context || EVP_DigestVerifyInit(context.get(), nullptr, nullptr, nullptr, key.get()) != 1)
            throw std::runtime_error("cannot initialize Ed25519 verification");
        if (EVP_DigestVerify(context.get(), signature.data(), signature.size(),
                             manifest.data(), manifest.size()) != 1)
            throw std::runtime_error("release signature verification failed");
        std::cout << "SIGNATURE_VERIFY_PASS algorithm=Ed25519 keyId=" << keyId << "\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "SIGNATURE_VERIFY_ERROR: " << error.what() << "\n";
        return 1;
    }
}
