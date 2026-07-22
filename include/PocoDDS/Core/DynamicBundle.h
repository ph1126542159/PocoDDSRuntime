#pragma once

#include "PocoDDS/Core/Bundle.h"

#include <filesystem>
#include <memory>

namespace PocoDDS::Core
{
class DynamicBundle final : public Bundle
{
  public:
    explicit DynamicBundle(const std::filesystem::path& libraryPath);
    ~DynamicBundle() override;

    DynamicBundle(const DynamicBundle&) = delete;
    DynamicBundle& operator=(const DynamicBundle&) = delete;

    std::string name() const override;
    void start(BundleContext& context) override;
    void stop(BundleContext& context) override;

    const std::filesystem::path& libraryPath() const;

  private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Core
