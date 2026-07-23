#pragma once

#include <string>

namespace PocoDDS::Protocols
{
class Protocol
{
public:
    virtual ~Protocol() = default;

    virtual std::string name() const = 0;
    virtual void open() = 0;
    virtual void close() noexcept = 0;
    virtual bool isOpen() const noexcept = 0;
};
} // namespace PocoDDS::Protocols
