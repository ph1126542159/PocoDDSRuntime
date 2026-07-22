#include "PocoDDS/CodeGeneration/ContractGenerator.h"
#include <gtest/gtest.h>

TEST(ContractGeneratorTest, GeneratesVersionableFastDdsIdl)
{
    PocoDDS::CodeGeneration::ContractGenerator generator;
    const auto idl = generator.generateIdl(
        {"Demo", "SurfaceFrame", {{"uint64", "sequence"}, {"string", "trace_parent"}}});
    EXPECT_NE(idl.find("struct SurfaceFrame"), std::string::npos);
    EXPECT_NE(idl.find("string trace_parent;"), std::string::npos);
}
