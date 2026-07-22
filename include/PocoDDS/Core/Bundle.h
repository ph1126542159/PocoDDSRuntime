#pragma once

#include <string>

namespace PocoDDS::Core
{
class BundleContext;

class Bundle
{
  public:
    virtual ~Bundle() = default;
    virtual std::string name() const = 0;
    virtual void start(BundleContext& context) = 0;
    virtual void stop(BundleContext& context) = 0;
};
} // namespace PocoDDS::Core
