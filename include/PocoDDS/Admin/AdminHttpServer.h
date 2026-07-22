#pragma once

#include "PocoDDS/Admin/AdminService.h"

#include <cstdint>
#include <memory>
#include <string>

namespace PocoDDS::Admin
{
struct AdminHttpOptions
{
    std::string bindAddress{"127.0.0.1"};
    std::uint16_t port{9080};
    std::string bearerToken;
    std::size_t maximumRequestBytes{1024 * 1024};
};

class AdminHttpServer
{
  public:
    AdminHttpServer(AdminService& service, AdminHttpOptions options);
    ~AdminHttpServer();

    AdminHttpServer(const AdminHttpServer&) = delete;
    AdminHttpServer& operator=(const AdminHttpServer&) = delete;

    void start();
    void stop();
    std::uint16_t port() const;

  private:
    class Impl;
    std::unique_ptr<Impl> _impl;
};
} // namespace PocoDDS::Admin
