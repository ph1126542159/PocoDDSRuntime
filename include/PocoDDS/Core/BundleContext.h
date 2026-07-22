#pragma once

#include "PocoDDS/Core/ComponentRegistry.h"

namespace PocoDDS::Core
{
class BundleContext
{
  public:
    explicit BundleContext(ComponentRegistry& registry) : _registry(registry) {}
    ComponentRegistry& registry() { return _registry; }

  private:
    ComponentRegistry& _registry;
};
} // namespace PocoDDS::Core
