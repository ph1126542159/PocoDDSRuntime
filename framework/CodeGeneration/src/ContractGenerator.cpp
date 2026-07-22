#include "PocoDDS/CodeGeneration/ContractGenerator.h"

#include <sstream>
#include <stdexcept>

namespace PocoDDS::CodeGeneration
{
std::string ContractGenerator::generateIdl(const Contract& contract) const
{
    if (contract.package.empty() || contract.name.empty())
        throw std::invalid_argument("contract package and name are required");
    std::ostringstream output;
    output << "module " << contract.package << "\n{\n    struct " << contract.name << "\n    {\n";
    for (const auto& field : contract.fields)
    {
        if (field.type.empty() || field.name.empty())
            throw std::invalid_argument("contract fields require type and name");
        output << "        " << field.type << ' ' << field.name << ";\n";
    }
    output << "    };\n};\n";
    return output.str();
}
} // namespace PocoDDS::CodeGeneration
