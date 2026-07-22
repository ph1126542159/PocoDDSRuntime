#pragma once

#include <string>
#include <vector>

namespace PocoDDS::CodeGeneration
{
struct Field
{
    std::string type;
    std::string name;
};

struct Contract
{
    std::string package;
    std::string name;
    std::vector<Field> fields;
};

class ContractGenerator
{
  public:
    std::string generateIdl(const Contract& contract) const;
};
} // namespace PocoDDS::CodeGeneration
