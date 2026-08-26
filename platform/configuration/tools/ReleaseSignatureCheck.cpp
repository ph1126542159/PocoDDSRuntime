#include "PocoDDS/Security/DetachedSignatureVerifier.h"

#include "Poco/Exception.h"

#include <iostream>
#include <string>

int main(int argc, char** argv)
{
    if (argc != 5 && argc != 6)
    {
        std::cerr << "usage: pdr-signature-check PAYLOAD SIGNATURE PUBLIC_KEY EXPECTED_KEY_ID [EXPECTED_PRODUCT]\n";
        return 2;
    }
    try
    {
        const std::string expectedProduct = argc == 6 ? argv[5] : "PocoDDSRuntime";
        const auto evidence = PocoDDS::Security::verifyEd25519DetachedSignature(
            argv[1], argv[2], argv[3], argv[4], expectedProduct);
        std::cout << "SIGNATURE_VERIFY_PASS algorithm=" << evidence.algorithm
                  << " keyId=" << evidence.keyId << '\n';
        return 0;
    }
    catch (const Poco::Exception& error)
    {
        std::cerr << "SIGNATURE_VERIFY_ERROR: " << error.displayText() << '\n';
        return 1;
    }
    catch (const std::exception& error)
    {
        std::cerr << "SIGNATURE_VERIFY_ERROR: " << error.what() << '\n';
        return 1;
    }
}
